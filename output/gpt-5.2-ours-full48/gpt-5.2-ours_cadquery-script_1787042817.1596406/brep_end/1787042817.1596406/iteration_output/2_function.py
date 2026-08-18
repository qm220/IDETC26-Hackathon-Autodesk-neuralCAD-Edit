def my_cad_function(args):
    import os, math
    import cadquery as cq

    input_file = os.path.expanduser(args.get("input_file", ""))
    if not input_file or not os.path.exists(input_file):
        raise ValueError(f"input_file not found: {input_file}")

    wp = cq.importers.importStep(input_file)
    shape = wp.val() if hasattr(wp, "val") else wp

    # ---------------- Vector helpers ----------------
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
            return (0.0, 0.0, 0.0)
        return (a[0] / L, a[1] / L, a[2] / L)

    def pt_tuple(p):
        return (float(p.x), float(p.y), float(p.z))

    def project_to_plane(vec, n):
        n = v_unit(n)
        return v_sub(vec, v_mul(n, v_dot(vec, n)))

    def plane_basis(axis_dir):
        n = v_unit(axis_dir)
        if v_len(n) < 1e-12:
            n = (0.0, 1.0, 0.0)
        x_guess = (1.0, 0.0, 0.0) if abs(n[0]) < 0.9 else (0.0, 0.0, 1.0)
        x_proj = v_mul(n, v_dot(x_guess, n))
        u = v_unit(v_sub(x_guess, x_proj))
        v = (
            n[1] * u[2] - n[2] * u[1],
            n[2] * u[0] - n[0] * u[2],
            n[0] * u[1] - n[1] * u[0],
        )
        v = v_unit(v)
        return u, v, n

    def dir_to_angle_deg(dir_in_plane, u, v):
        x = v_dot(dir_in_plane, u)
        y = v_dot(dir_in_plane, v)
        ang = math.degrees(math.atan2(y, x))
        return ang % 180.0

    def ang_dist_180(a, b):
        d = abs(a - b) % 180.0
        return min(d, 180.0 - d)

    def best_new_angle(existing_angles, step_deg=0.5):
        best_a = None
        best_score = -1.0
        a = 0.0
        while a < 180.0 - 1e-9:
            mind = min(ang_dist_180(a, ea) for ea in existing_angles)
            if mind > best_score:
                best_score = mind
                best_a = a
            a += step_deg
        return best_a, best_score

    # ---------------- Hub axis/radius detection ----------------
    def axis_from_smallest_bbox_dim(bb):
        dx, dy, dz = bb.xlen, bb.ylen, bb.zlen
        if dy <= dx and dy <= dz:
            return (0.0, 1.0, 0.0)
        if dx <= dy and dx <= dz:
            return (1.0, 0.0, 0.0)
        return (0.0, 0.0, 1.0)

    def find_hub_radius_and_axis(solids, global_center, axis_guess):
        try:
            from OCP.BRepAdaptor import BRepAdaptor_Surface
            from OCP.GeomAbs import GeomAbs_Cylinder
        except Exception:
            return None, axis_guess

        best = None  # (score, r, axis)
        ag = v_unit(axis_guess)

        for s in solids:
            for f in s.Faces():
                try:
                    ad = BRepAdaptor_Surface(f.wrapped)
                    if ad.GetType() != GeomAbs_Cylinder:
                        continue
                    cyl = ad.Cylinder()
                    r = float(cyl.Radius())
                    if r < 3.0 or r > 20.0:
                        continue
                    ax_dir = cyl.Axis().Direction()
                    ax = v_unit((float(ax_dir.X()), float(ax_dir.Y()), float(ax_dir.Z())))
                    align = abs(v_dot(ax, ag))
                    loc = cyl.Location()
                    c = (float(loc.X()), float(loc.Y()), float(loc.Z()))
                    dist = v_len(v_sub(c, global_center))
                    score = 10.0 * align - 0.10 * dist - 0.05 * abs(r - 6.5)
                    if best is None or score > best[0]:
                        best = (score, r, ax)
                except Exception:
                    continue

        if best is None:
            return None, axis_guess
        return best[1], best[2]

    # ---------------- Blade direction (in plane) ----------------
    def blade_dir_from_vertices(blade_solid, global_center, axis_dir):
        verts = blade_solid.Vertices()
        pts = []
        for vv in verts:
            p = pt_tuple(vv.Center())
            v0 = v_sub(p, global_center)
            vp = project_to_plane(v0, axis_dir)
            if v_len(vp) > 1e-6:
                pts.append(vp)
        if len(pts) < 2:
            bb = blade_solid.BoundingBox()
            return (0.0, 0.0, 1.0) if bb.zlen >= bb.xlen else (1.0, 0.0, 0.0)

        max_d2 = -1.0
        best_pair = (pts[0], pts[1])
        for i in range(len(pts)):
            a = pts[i]
            for j in range(i + 1, len(pts)):
                b = pts[j]
                d = v_sub(b, a)
                d2 = v_dot(d, d)
                if d2 > max_d2:
                    max_d2 = d2
                    best_pair = (a, b)
        d = v_unit(v_sub(best_pair[1], best_pair[0]))
        if v_len(d) < 1e-9:
            d = (0.0, 0.0, 1.0)
        return d

    # ---------------- Central thinning ----------------
    def make_axis_workplane(axis_dir):
        n = v_unit(axis_dir)
        if v_len(n) < 1e-12:
            n = (0.0, 1.0, 0.0)
        x_guess = (1.0, 0.0, 0.0) if abs(n[0]) < 0.9 else (0.0, 0.0, 1.0)
        x_proj = v_mul(n, v_dot(x_guess, n))
        xdir = v_unit(v_sub(x_guess, x_proj))
        if v_len(xdir) < 1e-12:
            xdir = (1.0, 0.0, 0.0)
        plane = cq.Plane(origin=(0, 0, 0), xDir=xdir, normal=n)
        return cq.Workplane(plane)

    def thin_central_portion(blade_solid, global_center, axis_dir, cut_radius, target_thickness=0.42):
        axis_dir = v_unit(axis_dir)
        if v_len(axis_dir) < 1e-12:
            axis_dir = (0.0, 1.0, 0.0)

        bb = blade_solid.BoundingBox()
        ax = (abs(axis_dir[0]), abs(axis_dir[1]), abs(axis_dir[2]))
        t0 = ax[0] * bb.xlen + ax[1] * bb.ylen + ax[2] * bb.zlen
        if t0 <= target_thickness + 1e-3:
            return blade_solid

        cutter_h = max(2.0 * t0, 40.0)
        base_wp = make_axis_workplane(axis_dir)
        cutter = base_wp.circle(cut_radius).extrude(cutter_h, both=True).val()

        offset = (target_thickness / 2.0) + (cutter_h / 2.0)
        top_cutter = cutter.translate(v_add(global_center, v_mul(axis_dir, offset)))
        bot_cutter = cutter.translate(v_add(global_center, v_mul(axis_dir, -offset)))
        return blade_solid.cut(top_cutter).cut(bot_cutter)

    # ---------------- Fillet long edges (robust selection from top/bottom outer faces) ----------------
    def dist_to_axis(pt, global_center, axis_dir):
        axis_dir = v_unit(axis_dir)
        v0 = v_sub(pt, global_center)
        vpar = v_mul(axis_dir, v_dot(v0, axis_dir))
        vper = v_sub(v0, vpar)
        return v_len(vper)

    def select_outer_top_bottom_faces(blade_solid, axis_dir):
        # Faces whose normals align with +/- axis_dir and whose centers are near the blade extremes along axis
        try:
            from OCP.BRepAdaptor import BRepAdaptor_Surface
            from OCP.GeomAbs import GeomAbs_Plane
        except Exception:
            return []

        axis_dir = v_unit(axis_dir)
        bb = blade_solid.BoundingBox()
        # approximate extremes along axis by projecting bbox corners isn't needed; axis is ~Y here.
        # Use dot of face center to find top/bottom.
        faces = []
        dots = []
        for f in blade_solid.Faces():
            try:
                ad = BRepAdaptor_Surface(f.wrapped)
                if ad.GetType() != GeomAbs_Plane:
                    continue
                pln = ad.Plane()
                dn = pln.Axis().Direction()
                n = v_unit((float(dn.X()), float(dn.Y()), float(dn.Z())))
                if abs(v_dot(n, axis_dir)) < 0.95:
                    continue
                c = pt_tuple(f.Center())
                d = v_dot(c, axis_dir)
                dots.append(d)
                faces.append((d, f))
            except Exception:
                continue

        if not faces:
            return []

        dmax = max(dots)
        dmin = min(dots)
        tol = 0.6  # mm
        out = []
        for d, f in faces:
            if abs(d - dmax) <= tol or abs(d - dmin) <= tol:
                out.append(f)
        return out

    def long_edges_from_faces(blade_solid, global_center, axis_dir, dlen, cut_radius, len_frac=0.12):
        dlen = v_unit(dlen)
        if v_len(dlen) < 1e-9:
            return []

        bb = blade_solid.BoundingBox()
        # in-plane span estimate
        inplane_span = max(bb.xlen, bb.zlen)
        min_len = max(20.0, len_frac * inplane_span)

        faces = select_outer_top_bottom_faces(blade_solid, axis_dir)
        edges = []
        for f in faces:
            try:
                ow = f.outerWire()
                for e in ow.Edges():
                    try:
                        L = float(e.Length())
                        if L < min_len:
                            continue
                        vs = e.Vertices()
                        if len(vs) < 2:
                            continue
                        p1 = pt_tuple(vs[0].Center())
                        p2 = pt_tuple(vs[-1].Center())
                        de = v_unit(v_sub(p2, p1))
                        if v_len(de) < 1e-12:
                            continue
                        if abs(v_dot(de, dlen)) < 0.85:
                            continue
                        mid = pt_tuple(e.Center())
                        if dist_to_axis(mid, global_center, axis_dir) < (cut_radius + 0.5):
                            continue
                        edges.append(e)
                    except Exception:
                        continue
            except Exception:
                continue

        # de-duplicate by hash
        uniq = {}
        for e in edges:
            try:
                hc = e.wrapped.HashCode(1000003)
            except Exception:
                hc = id(e)
            uniq[hc] = e
        edges = list(uniq.values())
        # keep longest first
        edges.sort(key=lambda ed: ed.Length(), reverse=True)
        return edges

    def fillet_edges_safe(solid, edges, radii_try):
        if not edges:
            return solid, False
        for r in radii_try:
            try:
                res = cq.Workplane(obj=solid).newObject(edges).fillet(r).val()
                return res, True
            except Exception as e:
                print(f"  fillet(r={r}) failed: {e}")
        # last resort: try per-edge fillets (partial success possible)
        s = solid
        any_ok = False
        for r in radii_try[::-1]:
            ok_local = True
            for e in edges:
                try:
                    s = cq.Workplane(obj=s).newObject([e]).fillet(r).val()
                    any_ok = True
                except Exception:
                    ok_local = False
                    continue
            if any_ok:
                return s, True
            if ok_local:
                return s, True
        return solid, False

    # ---------------- Main ----------------
    solids = list(shape.Solids()) if hasattr(shape, "Solids") else []
    print(f"Loaded STEP: {input_file}")
    print(f"Solid count (input): {len(solids)}")
    if len(solids) < 2:
        return wp

    bb_all = shape.BoundingBox()
    global_center = pt_tuple(bb_all.center)
    print(f"Overall bbox center: {global_center}")
    print(f"Overall bbox dims: dx={bb_all.xlen:.3f} dy={bb_all.ylen:.3f} dz={bb_all.zlen:.3f}")

    axis_guess = axis_from_smallest_bbox_dim(bb_all)
    hub_r, axis_dir = find_hub_radius_and_axis(solids, global_center, axis_guess)
    if hub_r is None:
        hub_r = 6.5
        axis_dir = (0.0, 1.0, 0.0)
    axis_dir = v_unit(axis_dir)
    if v_len(axis_dir) < 1e-12:
        axis_dir = (0.0, 1.0, 0.0)

    print(f"Axis dir (hub): {axis_dir}")
    print(f"Hub radius (detected/assumed): {hub_r:.3f} mm")

    # Identify blade solids
    blade_idxs = []
    non_blade_idxs = []
    for i, s in enumerate(solids):
        bb = s.BoundingBox()
        long_inplane = max(bb.xlen, bb.zlen)
        thin = bb.ylen
        # heuristic: long + thin
        if thin <= 20.0 and long_inplane >= 150.0:
            blade_idxs.append(i)
        else:
            non_blade_idxs.append(i)
        print(f"Solid[{i}] bb=({bb.xlen:.2f},{bb.ylen:.2f},{bb.zlen:.2f}) -> {'blade' if i in blade_idxs else 'other'}")

    if len(blade_idxs) < 2:
        # fallback: pick the 2 solids with biggest in-plane span / thickness ratio
        scored = []
        for i, s in enumerate(solids):
            bb = s.BoundingBox()
            long_inplane = max(bb.xlen, bb.zlen)
            ratio = long_inplane / max(bb.ylen, 1e-6)
            scored.append((ratio, long_inplane, i))
        scored.sort(reverse=True)
        blade_idxs = sorted([scored[0][2], scored[1][2]])
        non_blade_idxs = [i for i in range(len(solids)) if i not in blade_idxs]

    print(f"Blade solids selected: {blade_idxs}")
    print(f"Non-blade solids: {non_blade_idxs}")

    # Parameters
    target_t = 0.42
    cut_radius = float(hub_r + 2.0)
    # Fillet: not specified by user; choose modest and robust, with fallbacks
    radii_try = [1.0, 0.75, 0.5, 0.3, 0.2, 0.15, 0.1]

    u, v, n = plane_basis(axis_dir)

    modified = [None] * len(solids)
    blade_dirs = {}
    blade_angles = {}

    # Modify existing blades: thin central + fillet 4 long edges
    for i, s in enumerate(solids):
        if i not in blade_idxs:
            modified[i] = s
            continue

        b = s
        # thin central
        try:
            b = thin_central_portion(b, global_center, axis_dir, cut_radius, target_thickness=target_t)
            print(f"Blade[{i}] thinned: central thickness ~{target_t}mm within r={cut_radius:.3f}mm")
        except Exception as e:
            print(f"Blade[{i}] thinning failed: {e}")

        # direction + angle
        dlen = v_unit(blade_dir_from_vertices(b, global_center, axis_dir))
        blade_dirs[i] = dlen
        ang = dir_to_angle_deg(dlen, u, v)
        blade_angles[i] = ang
        print(f"Blade[{i}] dir_in_plane={dlen}, angle≈{ang:.2f}° (mod 180)")

        # fillet long edges
        edges = long_edges_from_faces(b, global_center, axis_dir, dlen, cut_radius, len_frac=0.12)
        print(f"Blade[{i}] long-edge candidates for fillet: {len(edges)}")
        b2, ok = fillet_edges_safe(b, edges, radii_try)
        print(f"Blade[{i}] fillet applied: {ok}")
        b = b2

        modified[i] = b

    # Choose template blade to duplicate (prefer the more 'in-plane' blade)
    def template_score(idx):
        bb = modified[idx].BoundingBox()
        return (bb.xlen + bb.zlen, max(bb.xlen, bb.zlen))

    template_idx = max(blade_idxs, key=template_score)
    template = modified[template_idx]

    # Place new blade through the stack center by rotating about hub axis through global_center
    template_dir = v_unit(blade_dir_from_vertices(template, global_center, axis_dir))
    template_ang = dir_to_angle_deg(template_dir, u, v)

    existing_angles = [blade_angles[idx] for idx in blade_idxs if idx in blade_angles]
    if not existing_angles:
        existing_angles = [template_ang]

    new_ang, gap = best_new_angle(existing_angles, step_deg=0.5)
    delta = new_ang - template_ang
    print(f"Template blade = Solid[{template_idx}], template_ang≈{template_ang:.2f}°; new_ang≈{new_ang:.2f}°; rotate delta≈{delta:.2f}° (gap≈{gap:.2f}°)")

    p1 = v_add(global_center, v_mul(axis_dir, -1000.0))
    p2 = v_add(global_center, v_mul(axis_dir, +1000.0))

    new_blade = template.copy() if hasattr(template, "copy") else template
    try:
        new_blade = new_blade.rotate(p1, p2, delta)
    except Exception as e:
        print(f"New blade rotation failed ({e}); using 60° fallback")
        new_blade = new_blade.rotate(p1, p2, 60.0)

    # Ensure new blade also has thinning (template already should) + attempt fillet again after rotate (safety)
    try:
        new_blade = thin_central_portion(new_blade, global_center, axis_dir, cut_radius, target_thickness=target_t)
    except Exception as e:
        print(f"New blade thinning ensure failed: {e}")

    try:
        dlen_new = v_unit(blade_dir_from_vertices(new_blade, global_center, axis_dir))
        edges_new = long_edges_from_faces(new_blade, global_center, axis_dir, dlen_new, cut_radius, len_frac=0.12)
        print(f"New blade long-edge candidates for fillet: {len(edges_new)}")
        new_blade2, ok_new = fillet_edges_safe(new_blade, edges_new, radii_try)
        print(f"New blade fillet applied: {ok_new}")
        new_blade = new_blade2
    except Exception as e:
        print(f"New blade fillet ensure failed: {e}")

    out_solids = [modified[i] for i in range(len(solids)) if modified[i] is not None]
    out_solids.append(new_blade)

    print(f"Solid count (output): {len(out_solids)}")
    return cq.Compound.makeCompound(out_solids)
