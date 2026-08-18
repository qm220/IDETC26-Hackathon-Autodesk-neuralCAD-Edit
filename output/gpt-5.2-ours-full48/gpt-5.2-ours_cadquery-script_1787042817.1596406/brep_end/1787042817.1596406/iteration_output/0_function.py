def my_cad_function(args):
    import os, math
    import cadquery as cq

    # --- Load STEP ---
    input_file = os.path.expanduser(args.get("input_file", ""))
    if not input_file or not os.path.exists(input_file):
        raise ValueError(f"input_file not found: {input_file}")

    wp = cq.importers.importStep(input_file)
    shape = wp.val() if hasattr(wp, "val") else wp

    # --- Helpers ---
    def v_add(a, b):
        return (a[0] + b[0], a[1] + b[1], a[2] + b[2])

    def v_sub(a, b):
        return (a[0] - b[0], a[1] - b[1], a[2] - b[2])

    def v_mul(a, s):
        return (a[0] * s, a[1] * s, a[2] * s)

    def v_dot(a, b):
        return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]

    def v_len(a):
        return math.sqrt(max(0.0, v_dot(a, a)))

    def v_unit(a):
        L = v_len(a)
        if L < 1e-12:
            return (0.0, 0.0, 1.0)
        return (a[0] / L, a[1] / L, a[2] / L)

    def bbox_dims(bb):
        return (bb.xlen, bb.ylen, bb.zlen)

    def axis_from_smallest_bbox_dim(bb):
        # Heuristic: stack axis is usually the smallest overall dimension
        dx, dy, dz = bbox_dims(bb)
        if dx <= dy and dx <= dz:
            return (1.0, 0.0, 0.0)
        if dy <= dx and dy <= dz:
            return (0.0, 1.0, 0.0)
        return (0.0, 0.0, 1.0)

    def proj_extent_along_axis(bb, axis):
        # Since bb is axis-aligned, we approximate projection extent by taking component axis aligned.
        ax = tuple(map(abs, axis))
        dx, dy, dz = bbox_dims(bb)
        return ax[0] * dx + ax[1] * dy + ax[2] * dz

    def make_axis_workplane(axis_dir):
        n = v_unit(axis_dir)
        # choose an xDir not parallel to n
        x_guess = (1.0, 0.0, 0.0) if abs(n[0]) < 0.9 else (0.0, 1.0, 0.0)
        # Gram-Schmidt to make xDir perpendicular to n
        x_proj = v_mul(n, v_dot(x_guess, n))
        xdir = v_unit(v_sub(x_guess, x_proj))
        plane = cq.Plane(origin=(0, 0, 0), xDir=xdir, normal=n)
        return cq.Workplane(plane)

    def find_hub_radius_and_axis(solids, global_center, axis_guess):
        """Try to detect a central cylindrical face and its radius. Falls back to None."""
        try:
            from OCP.BRepAdaptor import BRepAdaptor_Surface
            from OCP.GeomAbs import GeomAbs_Cylinder
        except Exception:
            print("OCP not available for cylinder detection; using fallback hub radius.")
            return None, axis_guess

        best = None  # (score, radius, axis_dir)
        axis_guess_u = v_unit(axis_guess)

        for s in solids:
            try:
                faces = s.Faces()
            except Exception:
                continue
            for f in faces:
                try:
                    ad = BRepAdaptor_Surface(f.wrapped)
                    if ad.GetType() != GeomAbs_Cylinder:
                        continue
                    cyl = ad.Cylinder()
                    r = float(cyl.Radius())
                    ax_dir = cyl.Axis().Direction()
                    ax = v_unit((float(ax_dir.X()), float(ax_dir.Y()), float(ax_dir.Z())))

                    # prefer cylinders whose axis aligns with our axis_guess
                    align = abs(v_dot(ax, axis_guess_u))

                    # prefer cylinders near center
                    loc = cyl.Location()
                    c = (float(loc.X()), float(loc.Y()), float(loc.Z()))
                    dist = v_len(v_sub(c, global_center))

                    # score: alignment high, radius moderate, dist small
                    score = (align * 10.0) - (dist * 0.05) + (min(r, 50.0) * 0.01)
                    if best is None or score > best[0]:
                        best = (score, r, ax)
                except Exception:
                    continue

        if best is None:
            return None, axis_guess
        return best[1], best[2]

    def longest_line_edges(solid, min_len):
        # Return line edges longer than min_len (heuristic for the 4 long edges)
        try:
            from OCP.BRepAdaptor import BRepAdaptor_Curve
            from OCP.GeomAbs import GeomAbs_Line
        except Exception:
            # fallback: just use length-based selection without checking curve type
            edges = solid.edges().vals()
            return [e for e in edges if e.Length() > min_len]

        sel = []
        for e in solid.edges().vals():
            try:
                ad = BRepAdaptor_Curve(e.wrapped)
                if ad.GetType() != GeomAbs_Line:
                    continue
                if e.Length() > min_len:
                    sel.append(e)
            except Exception:
                continue
        return sel

    def thin_central_portion(blade_solid, global_center, axis_dir, cut_radius, target_thickness=0.42):
        """Thin a central circular region (around global_center) by cutting from both sides along axis_dir."""
        bb = blade_solid.BoundingBox()
        axis_dir = v_unit(axis_dir)

        # approximate current thickness along axis using bbox projection
        t0 = proj_extent_along_axis(bb, axis_dir)
        if t0 <= target_thickness + 1e-3:
            return blade_solid

        cutter_h = max(2.0 * t0, 10.0)  # tall enough to remove the outer halves

        # build cutters aligned with axis_dir
        base_wp = make_axis_workplane(axis_dir)
        cutter = base_wp.circle(cut_radius).extrude(cutter_h, both=True).val()

        # place cutters so they remove everything above +target/2 and below -target/2
        offset = (target_thickness / 2.0) + (cutter_h / 2.0)
        top_cutter = cutter.translate(v_add(global_center, v_mul(axis_dir, offset)))
        bot_cutter = cutter.translate(v_add(global_center, v_mul(axis_dir, -offset)))

        out = blade_solid.cut(top_cutter).cut(bot_cutter)
        return out

    def add_third_blade(template_blade, global_center, axis_dir, existing_blades):
        """Duplicate template_blade and rotate it about axis to fill missing 3-blade spacing."""
        axis_dir = v_unit(axis_dir)

        # Determine blade direction vectors in plane from bbox centers
        def blade_dir(b):
            c = b.BoundingBox().center
            v = (c.x - global_center[0], c.y - global_center[1], c.z - global_center[2])
            # remove axis component
            v_par = v_mul(axis_dir, v_dot(v, axis_dir))
            v_pl = v_sub(v, v_par)
            return v_unit(v_pl)

        d0 = blade_dir(existing_blades[0])
        d1 = blade_dir(existing_blades[1])
        # angle between in plane
        dot01 = max(-1.0, min(1.0, v_dot(d0, d1)))
        ang = math.degrees(math.acos(dot01))
        print(f"Existing blade angle (heuristic) = {ang:.2f} deg")

        # Heuristic: assume missing blade for 3-blade rotor -> use +120 from blade0, unless too close to blade1
        angle_try = 120.0

        # Build rotation axis line
        p1 = v_add(global_center, v_mul(axis_dir, -1000.0))
        p2 = v_add(global_center, v_mul(axis_dir, +1000.0))

        new_blade = template_blade.copy() if hasattr(template_blade, "copy") else template_blade
        new_blade = new_blade.rotate(p1, p2, angle_try)

        return new_blade

    # --- Analyze solids ---
    solids = list(shape.Solids()) if hasattr(shape, "Solids") else []
    print(f"Loaded STEP: {input_file}")
    print(f"Solid count: {len(solids)}")
    bb_all = shape.BoundingBox()
    c_all = bb_all.center
    global_center = (float(c_all.x), float(c_all.y), float(c_all.z))
    dx, dy, dz = bbox_dims(bb_all)
    print(f"Overall bbox dims: dx={dx:.3f} dy={dy:.3f} dz={dz:.3f}")
    print(f"Overall bbox center: {global_center}")

    if len(solids) < 2:
        # Not enough separate bodies to safely proceed; return unchanged but with debug.
        print("WARNING: Fewer than 2 solids found; cannot reliably identify two blades as separate bodies.")
        return wp

    # Rotation/stack axis guess from smallest overall dimension
    axis_guess = axis_from_smallest_bbox_dim(bb_all)
    hub_r, axis_dir = find_hub_radius_and_axis(solids, global_center, axis_guess)
    if hub_r is None:
        hub_r = 10.0  # fallback
        axis_dir = axis_guess
    print(f"Axis dir (heuristic) = {axis_dir}")
    print(f"Hub radius (heuristic) = {hub_r:.3f} mm")

    # Identify blade candidates by elongation ratio
    candidates = []
    for i, s in enumerate(solids):
        bb = s.BoundingBox()
        ext_ax = proj_extent_along_axis(bb, axis_dir)
        # planar extents approx = max of the two remaining bbox dims
        dxs, dys, dzs = bbox_dims(bb)
        planar = sorted([dxs, dys, dzs], reverse=True)
        max_dim = planar[0]
        min_dim = planar[2]
        ratio = max_dim / max(min_dim, 1e-6)
        candidates.append((max_dim, ratio, ext_ax, i, s))
        print(f"Solid[{i}] bbox: ({dxs:.2f},{dys:.2f},{dzs:.2f})  max_dim={max_dim:.2f} ratio={ratio:.2f} ax_ext={ext_ax:.2f}")

    # pick two most 'blade-like': largest max_dim with good ratio
    candidates.sort(key=lambda t: (t[0], t[1]), reverse=True)
    blade1 = candidates[0][4]
    blade2 = candidates[1][4]
    blade_idxs = {candidates[0][3], candidates[1][3]}
    print(f"Selected blade solids (heuristic): {sorted(list(blade_idxs))}")

    # Fillet radius (not specified in request). Start small.
    fillet_r = 0.5

    # Central thinning
    target_t = 0.42
    cut_radius = float(hub_r + 2.0)  # central portion region to thin

    modified_solids = []
    blade_solids = []
    for i, s in enumerate(solids):
        if i in blade_idxs:
            b = s
            # Thin central portion
            try:
                b = thin_central_portion(b, global_center, axis_dir, cut_radius, target_thickness=target_t)
                print(f"Blade[{i}] thinned central portion to ~{target_t} mm within r={cut_radius}.")
            except Exception as e:
                print(f"Blade[{i}] thinning failed: {e}")

            # Fillet the long edges (heuristic: longest LINE edges)
            try:
                # Determine edge length threshold from blade bbox
                bb = b.BoundingBox()
                dims = bbox_dims(bb)
                Lref = max(dims)
                min_len = 0.60 * Lref
                edges_sel = longest_line_edges(cq.Workplane(obj=b).val(), min_len)
                print(f"Blade[{i}] candidate long line edges: {len(edges_sel)} (min_len={min_len:.2f})")

                if len(edges_sel) >= 4:
                    # fillet on the 4 longest edges
                    edges_sel = sorted(edges_sel, key=lambda e: e.Length(), reverse=True)[:4]
                elif len(edges_sel) == 0:
                    edges_sel = []

                if edges_sel:
                    b_wp = cq.Workplane(obj=b).edges(cq.selectors.NearestToPointSelector(edges_sel[0].Center())).fillet(fillet_r)
                    # The above only fillets one edge; instead use direct edge objects selection via .newObject
                    # Rebuild robustly:
                    b_wp = cq.Workplane(obj=b).newObject(edges_sel).fillet(fillet_r)
                    b = b_wp.val()
                    print(f"Blade[{i}] filleted {len(edges_sel)} long edges with r={fillet_r}.")
                else:
                    print(f"Blade[{i}] no suitable long edges found for fillet.")
            except Exception as e:
                print(f"Blade[{i}] fillet failed: {e}")

            modified_solids.append(b)
            blade_solids.append(b)
        else:
            modified_solids.append(s)

    # Add third blade, same design as blade1 after modifications
    try:
        new_blade = add_third_blade(blade_solids[0], global_center, axis_dir, blade_solids)
        # Ensure new blade also has central thinning + fillets (in case rotation changed selection requirements)
        try:
            new_blade = thin_central_portion(new_blade, global_center, axis_dir, cut_radius, target_thickness=target_t)
        except Exception:
            pass

        # Try fillet on new blade (again)
        try:
            bb = new_blade.BoundingBox()
            Lref = max(bbox_dims(bb))
            min_len = 0.60 * Lref
            edges_sel = longest_line_edges(cq.Workplane(obj=new_blade).val(), min_len)
            if len(edges_sel) >= 4:
                edges_sel = sorted(edges_sel, key=lambda e: e.Length(), reverse=True)[:4]
            if edges_sel:
                new_blade = cq.Workplane(obj=new_blade).newObject(edges_sel).fillet(fillet_r).val()
        except Exception as e:
            print(f"New blade fillet failed: {e}")

        modified_solids.append(new_blade)
        print("Added third blade (duplicated + rotated).")
    except Exception as e:
        print(f"Failed to add third blade: {e}")

    # Return as compound to preserve multi-solid structure
    result = cq.Compound.makeCompound(modified_solids)
    return result
