def my_cad_function(args):
    import cadquery as cq
    import os, math
    from cadquery.selectors import PredicateSelector

    input_file = args.get("input_file", None)
    if not input_file:
        raise ValueError("Expected args['input_file']")
    step_path = os.path.expanduser(input_file)
    if not os.path.exists(step_path):
        raise ValueError(f"STEP file not found: {step_path}")

    imp = cq.importers.importStep(step_path)
    wp0 = imp if isinstance(imp, cq.Workplane) else cq.Workplane(obj=imp)
    sh = wp0.val()

    # Prefer single solid if available
    try:
        solids = list(sh.Solids())
    except Exception:
        solids = []
    base = solids[0] if len(solids) == 1 else sh

    bbox = base.BoundingBox()
    print("Loaded STEP:", step_path)
    print(f"BBOX xmin/xmax: {bbox.xmin:.3f}, {bbox.xmax:.3f}")
    print(f"BBOX ymin/ymax: {bbox.ymin:.3f}, {bbox.ymax:.3f}")
    print(f"BBOX zmin/zmax: {bbox.zmin:.3f}, {bbox.zmax:.3f}")

    faces = list(base.Faces())

    def _safe_normal(face):
        try:
            n = face.normalAt()
            return cq.Vector(n.x, n.y, n.z)
        except Exception:
            try:
                ad = face._geomAdaptor()
                if face.geomType() == "PLANE":
                    pln = ad.Plane()
                    d = pln.Axis().Direction()
                    return cq.Vector(d.X(), d.Y(), d.Z())
            except Exception:
                pass
        return cq.Vector(0, 0, 0)

    def _axis_is_y(ax: cq.Vector):
        return abs(ax.y) > 0.92 and abs(ax.x) < 0.35 and abs(ax.z) < 0.35

    # --- detect arm side planes (Y) and thickness planes (Z) ---
    plane_faces_y = []
    plane_faces_z = []
    for f in faces:
        if f.geomType() != "PLANE":
            continue
        n = _safe_normal(f)
        c = f.Center()
        a = f.Area()
        if abs(n.y) > 0.95 and abs(n.x) < 0.25 and abs(n.z) < 0.25:
            plane_faces_y.append((a, c.y))
        if abs(n.z) > 0.95 and abs(n.x) < 0.25 and abs(n.y) < 0.25:
            plane_faces_z.append((a, c.z))

    plane_faces_y.sort(reverse=True, key=lambda t: t[0])
    plane_faces_z.sort(reverse=True, key=lambda t: t[0])

    if len(plane_faces_y) >= 2:
        y_lower, y_upper = sorted([plane_faces_y[0][1], plane_faces_y[1][1]])
    else:
        y_lower, y_upper = bbox.ymin, bbox.ymax

    if len(plane_faces_z) >= 2:
        z_bottom, z_top = sorted([plane_faces_z[0][1], plane_faces_z[1][1]])
    else:
        z_bottom, z_top = bbox.zmin, bbox.zmax

    print(f"Detected arm Y side planes: y_lower={y_lower:.3f}, y_upper={y_upper:.3f}")
    print(f"Detected arm Z planes: z_bottom={z_bottom:.3f}, z_top={z_top:.3f}")

    # --- detect boss + bore cylinders (axis ~Y) ---
    cyl_info = []
    for f in faces:
        if f.geomType() != "CYLINDER":
            continue
        try:
            ad = f._geomAdaptor()
            cyl = ad.Cylinder()
            r = float(cyl.Radius())
            d = cyl.Axis().Direction()
            axis = cq.Vector(d.X(), d.Y(), d.Z())
            c = f.Center()
            bb = f.BoundingBox()
            cyl_info.append((r, axis, c, bb))
        except Exception:
            continue

    boss_cands = [ci for ci in cyl_info if _axis_is_y(ci[1]) and 6.3 <= ci[0] <= 7.7]
    bore_cands = [ci for ci in cyl_info if _axis_is_y(ci[1]) and 4.3 <= ci[0] <= 5.7]

    if not boss_cands:
        raise ValueError("Could not find boss outer cylinder (r~7, axis~Y).")
    if not bore_cands:
        raise ValueError("Could not find bore cylinder (r~5, axis~Y).")

    # choose boss candidate with highest ymax (mouth end)
    boss_cands.sort(key=lambda t: t[3].ymax, reverse=True)
    boss_r, boss_axis, boss_center, boss_bb = boss_cands[0]

    # choose bore candidate closest in XZ to boss
    def _xz_dist(ci):
        c = ci[2]
        return (c.x - boss_center.x) ** 2 + (c.z - boss_center.z) ** 2

    bore_cands.sort(key=_xz_dist)
    bore_r, bore_axis, bore_center, bore_bb = bore_cands[0]

    x0 = float(boss_center.x)
    z0 = float(boss_center.z)
    y_top = float(boss_bb.ymax)
    y_boss_min = float(boss_bb.ymin)
    bore_ymin = float(bore_bb.ymin)

    print(
        f"Boss detected: r_outer={boss_r:.3f}, center=({x0:.3f},{boss_center.y:.3f},{z0:.3f}), y_min={y_boss_min:.3f}, y_top={y_top:.3f}"
    )
    print(f"Bore detected: r_inner={bore_r:.3f}, bore_ymin={bore_ymin:.3f}")

    # --- compute 4 boss X locations (keep original at x0, add 3 to +X) ---
    right_clear = float(bbox.xmax - (boss_r + 3.0))
    if right_clear <= x0 + 3.0:
        right_clear = x0 + 3.0

    span = max(1e-6, right_clear - x0)
    dx = span / 3.0
    x_positions = [x0 + i * dx for i in range(4)]

    tol = 0.25
    new_x_positions = [xp for xp in x_positions if abs(xp - x0) > tol]

    print("Boss pattern x positions (target 4 total):", [round(v, 3) for v in x_positions])
    print("New boss x positions to add:", [round(v, 3) for v in new_x_positions])

    res = base

    # --- Add 3 new bosses (outer cylinder) and cut bores ---
    # Embed slightly into the arm to guarantee intersection (avoid disconnected solids)
    embed = 2.0
    y_start = min(y_upper, y_boss_min) - embed
    boss_h = y_top - y_start
    if boss_h <= 0:
        raise ValueError("Computed boss height is non-positive; check detection.")

    bore_len = max(0.2, y_top - bore_ymin)

    for xp in new_x_positions:
        boss_solid = (
            cq.Workplane("XZ")
            .workplane(offset=y_start)
            .center(xp, z0)
            .circle(boss_r)
            .extrude(boss_h)
        ).val()
        res = res.fuse(boss_solid)

        bore_cut = (
            cq.Workplane("XZ")
            .workplane(offset=bore_ymin)
            .center(xp, z0)
            .circle(bore_r)
            .extrude(bore_len)
        ).val()
        res = res.cut(bore_cut)

    result = cq.Workplane(obj=res)

    # --- Add stability ribs / gussets on both long sides (y=y_upper and y=y_lower) ---
    rib_out = 6.0
    rib_overlap = 0.6
    x_half_base = boss_r + 5.0
    x_half_top = boss_r + 1.5

    def _rib_profile(xp):
        # Trapezoid in XZ spanning arm thickness
        return [
            (xp - x_half_base, z_bottom),
            (xp + x_half_base, z_bottom),
            (xp + x_half_top, z_top),
            (xp - x_half_top, z_top),
        ]

    for xp in x_positions:
        prof = _rib_profile(xp)

        # +Y side rib
        rib_plus = (
            cq.Workplane("XZ")
            .workplane(offset=y_upper - rib_overlap)
            .polyline(prof)
            .close()
            .extrude(rib_out + rib_overlap)
        ).val()
        result = result.union(cq.Workplane(obj=rib_plus))

        # -Y side rib
        rib_minus = (
            cq.Workplane("XZ")
            .workplane(offset=y_lower + rib_overlap)
            .polyline(prof)
            .close()
            .extrude(-(rib_out + rib_overlap))
        ).val()
        result = result.union(cq.Workplane(obj=rib_minus))

    # --- Fillet boss/arm sharp intersection for NEW bosses (best-effort) ---
    # Apply only near y=y_upper to avoid global fillet failures.
    def _edge_is_boss_exit_circle(e, xp):
        try:
            if e.geomType() != "CIRCLE":
                return False
            c = e.Center()
            if abs(c.x - xp) > 1.5:
                return False
            if abs(c.y - y_upper) > 1.2:
                return False
            ad = e._geomAdaptor()
            r = float(ad.Circle().Radius())
            return abs(r - boss_r) < 0.6
        except Exception:
            return False

    fillet_r = 2.0
    for xp in new_x_positions:
        try:
            sel = PredicateSelector(lambda e, xpp=xp: _edge_is_boss_exit_circle(e, xpp))
            result = result.edges(sel).fillet(fillet_r)
        except Exception as e:
            print(f"Local boss fillet failed at x={xp:.3f} (non-fatal):", e)

    # Small fillet at rib roots near both side planes (best-effort)
    try:
        def _rib_root_edge(e):
            try:
                c = e.Center()
                return (abs(c.y - y_upper) < 0.9 or abs(c.y - y_lower) < 0.9) and e.Length() > 2.0
            except Exception:
                return False

        result = result.edges(PredicateSelector(_rib_root_edge)).fillet(0.6)
    except Exception as e:
        print("Rib root fillet failed (non-fatal):", e)

    # Debug: verify approx 4 outer-boss cylinders + 4 bore cylinders by unique X
    try:
        out_x = []
        in_x = []
        for f in result.val().Faces():
            if f.geomType() != "CYLINDER":
                continue
            ad = f._geomAdaptor()
            cyl = ad.Cylinder()
            r = float(cyl.Radius())
            d = cyl.Axis().Direction()
            ax = cq.Vector(d.X(), d.Y(), d.Z())
            if not _axis_is_y(ax):
                continue
            cx = round(f.Center().x / 0.5) * 0.5
            if abs(r - boss_r) < 0.5:
                out_x.append(cx)
            if abs(r - bore_r) < 0.5:
                in_x.append(cx)
        out_uniq = sorted(set(out_x))
        in_uniq = sorted(set(in_x))
        print("Post-op unique outer-boss-cylinder X positions:", out_uniq)
        print("Post-op unique bore-cylinder X positions:", in_uniq)
    except Exception as e:
        print("Post-op cylinder check failed (non-fatal):", e)

    try:
        result = result.clean()
    except Exception:
        pass

    return result
