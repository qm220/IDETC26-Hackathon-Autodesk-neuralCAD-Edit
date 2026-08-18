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

    def v_cross(a, b):
        return (
            a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0],
        )

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
        v = v_unit(v_cross(n, u))
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
                    if r < 3.0 or r > 25.0:
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

        cutter_h = max(2.0 * t0, 60.0)
        base_wp = make_axis_workplane(axis_dir)
        cutter = base_wp.circle(cut_radius).extrude(cutter_h, both=True).val()

        # Place two cutters far away so they remove everything beyond +/- target_thickness/2, leaving a thin web
        offset = (target_thickness / 2.0) + (cutter_h / 2.0)
        top_cutter = cutter.translate(v_add(global_center, v_mul(axis_dir, offset)))
        bot_cutter = cutter.translate(v_add(global_center, v_mul(axis_dir, -offset)))
        return blade_solid.cut(top_cutter).cut(bot_cutter)

    # ---------------- Fillet: select four long edges robustly from all edges ----------------
    def dist_to_axis(pt, global_center, axis_dir):
        axis_dir = v_unit(axis_dir)
        v0 = v_sub(pt, global_center)
        vpar = v_mul(axis_dir, v_dot(v0, axis_dir))
        vper = v_sub(v0, vpar)
        return v_len(vper)

    def edge_endpoints(edge):
        vs = edge.Vertices()
        if len(vs) < 2:
            p = pt_tuple(edge.Center())
            return p, p
        return pt_tuple(vs[0].Center()), pt_tuple(vs[-1].Center())

    def proj_span_along_axis(blade_solid, axis_dir):
        axis_dir = v_unit(axis_dir)
        ds = []
        for vv in blade_solid.Vertices():
            p = pt_tuple(vv.Center())
            ds.append(v_dot(p, axis_dir))
        if not ds:
            c = pt_tuple(blade_solid.Center())
            d = v_dot(c, axis_dir)
            return d, d
        return min(ds), max(ds)

    def select_four_long_edges(blade_solid, global_center, axis_dir, dlen, cut_radius, topbot_tol=0.9):
        axis_dir = v_unit(axis_dir)
        dlen = v_unit(dlen)
        if v_len(dlen) < 1e-9:
            return []

        # transverse direction in rotor plane
        w = v_unit(v_cross(axis_dir, dlen))
        if v_len(w) < 1e-9:
            # fallback: any perpendicular vector
            u, v, _ = plane_basis(axis_dir)
            w = v_unit(v_cross(axis_dir, u))

        hmin, hmax = proj_span_along_axis(blade_solid, axis_dir)

        bb = blade_solid.BoundingBox()
        inplane_span = max(bb.xlen, bb.zlen)
        min_len = max(25.0, 0.12 * inplane_span)

        top_cands = []
        bot_cands = []

        all_edges = list(blade_solid.Edges())
        for e in all_edges:
            try:
                L = float(e.Length())
                if L < min_len:
                    continue

                p1, p2 = edge_endpoints(e)
                de = v_unit(v_sub(p2, p1))
                if v_len(de) < 1e-12:
                    continue

                if abs(v_dot(de, dlen)) < 0.85:
                    continue

                mid = pt_tuple(e.Center())

                # avoid central thinned region boundary edges
                if dist_to_axis(mid, global_center, axis_dir) < (cut_radius + 0.6):
                    continue

                h = v_dot(mid, axis_dir)
                is_top = abs(h - hmax) <= topbot_tol
                is_bot = abs(h - hmin) <= topbot_tol
                if not (is_top or is_bot):
                    continue

                s = v_dot(v_sub(mid, global_center), w)

                # hash for uniqueness
                try:
                    hc = e.wrapped.HashCode(1000003)
                except Exception:
                    hc = id(e)

                item = (s, L, hc, e)
                if is_top:
                    top_cands.append(item)
                if is_bot:
                    bot_cands.append(item)
            except Exception:
                continue

        def pick_two(cands):
            if not cands:
                return []
            # unique by hash, keep longest for each hash
            by = {}
            for s, L, hc, e in cands:
                if hc not in by or L > by[hc][1]:
                    by[hc] = (s, L, hc, e)
            items = list(by.values())
            if len(items) == 1:
                return [items[0][3]]
            # pick most positive and most negative s
            pos = max(items, key=lambda t: t[0])
            neg = min(items, key=lambda t: t[0])
            if pos[2] == neg[2]:
                # fallback: two longest
                items.sort(key=lambda t: t[1], reverse=True)
                return [items[0][3], items[1][3]]
            return [neg[3], pos[3]]

        picked = pick_two(top_cands) + pick_two(bot_cands)
        # de-dup
        uniq = {}
        for e in picked:
            try:
                hc = e.wrapped.HashCode(1000003)
            except Exception:
                hc = id(e)
            uniq[hc] = e
        return list(uniq.values())

    def fillet_edges_safe(solid, edges, radii_try):
        if not edges:
            return solid, False
        # First: attempt all at once
        for r in radii_try:
            try:
                res = cq.Workplane(obj=solid).newObject(edges).fillet(r).val()
                return res, True
            except Exception as e:
                print(f"  fillet(all, r={r}) failed: {e}")
        # Second: attempt per-edge (keep any successes)
        s = solid
        any_ok = False
        for r in radii_try[::-1]:
            for e in edges:
                try:
                    s = cq.Workplane(obj=s).newObject([e]).fillet(r).val()
                    any_ok = True
                except Exception:
                    pass
            if any_ok:
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
        if thin <= 20.0 and long_inplane >= 150.0:
            blade_idxs.append(i)
        else:
            non_blade_idxs.append(i)
        print(f"Solid[{i}] bb=({bb.xlen:.2f},{bb.ylen:.2f},{bb.zlen:.2f}) -> {'blade' if i in blade_idxs else 'other'}")

    if len(blade_idxs) < 2:
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
    cut_radius = float(hub_r + 2.0)  # thinning footprint
    radii_try = [1.0, 0.75, 0.5, 0.35, 0.25, 0.2, 0.15, 0.1]

    u, v, n = plane_basis(axis_dir)

    modified = [None] * len(solids)
    blade_angles = {}

    # Modify existing blades: thin central + fillet four long edges
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
        ang = dir_to_angle_deg(dlen, u, v)
        blade_angles[i] = ang
        print(f"Blade[{i}] dir_in_plane={dlen}, angle≈{ang:.2f}° (mod 180)")

        # fillet: pick 4 long edges
        edges4 = select_four_long_edges(b, global_center, axis_dir, dlen, cut_radius, topbot_tol=1.1)
        print(f"Blade[{i}] selected long edges for fillet: {len(edges4)}")
        b2, ok = fillet_edges_safe(b, edges4, radii_try)
        print(f"Blade[{i}] fillet applied: {ok}")
        b = b2

        modified[i] = b

    # Choose template blade to duplicate (pick blade with biggest in-plane span)
    def template_score(idx):
        bb = modified[idx].BoundingBox()
        return max(bb.xlen, bb.zlen)

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
    print(
        f"Template blade = Solid[{template_idx}], template_ang≈{template_ang:.2f}°; "
        f"new_ang≈{new_ang:.2f}°; rotate delta≈{delta:.2f}° (gap≈{gap:.2f}°)"
    )

    p1 = v_add(global_center, v_mul(axis_dir, -1000.0))
    p2 = v_add(global_center, v_mul(axis_dir, +1000.0))

    new_blade = template.copy() if hasattr(template, "copy") else template
    try:
        new_blade = new_blade.rotate(p1, p2, delta)
    except Exception as e:
        print(f"New blade rotation failed ({e}); using 60° fallback")
        new_blade = new_blade.rotate(p1, p2, 60.0)

    # Output: original non-blade solids + modified blades + new blade
    out_solids = [modified[i] for i in range(len(solids)) if modified[i] is not None]
    out_solids.append(new_blade)

    print(f"Solid count (output): {len(out_solids)}")
    return cq.Compound.makeCompound(out_solids)
