def my_cad_function(args):
    import cadquery as cq
    import os, math

    input_file = args.get("input_file", None)
    if not input_file:
        raise ValueError("Expected args['input_file']")
    step_path = os.path.expanduser(input_file)
    if not os.path.exists(step_path):
        raise ValueError(f"STEP file not found: {step_path}")

    imp = cq.importers.importStep(step_path)
    wp0 = imp if isinstance(imp, cq.Workplane) else cq.Workplane(obj=imp)
    sh = wp0.val()

    # Prefer working from a single solid if the STEP imported as a compound
    solids = []
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

    def _axis_is_y(ax: cq.Vector):
        return abs(ax.y) > 0.92 and abs(ax.x) < 0.35 and abs(ax.z) < 0.35

    boss_cands = [ci for ci in cyl_info if _axis_is_y(ci[1]) and 6.3 <= ci[0] <= 7.7]
    bore_cands = [ci for ci in cyl_info if _axis_is_y(ci[1]) and 4.3 <= ci[0] <= 5.7]

    if not boss_cands:
        raise ValueError("Could not find boss outer cylinder (r~7, axis~Y).")
    if not bore_cands:
        raise ValueError("Could not find bore cylinder (r~5, axis~Y).")

    # choose boss candidate highest in Y extent
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
    y_top = float(boss_bb.ymax)        # ~34
    bore_ymin = float(bore_bb.ymin)    # ~25

    print(
        f"Boss detected: r_outer={boss_r:.3f}, center=({x0:.3f},{boss_center.y:.3f},{z0:.3f}), y_top={y_top:.3f}"
    )
    print(f"Bore detected: r_inner={bore_r:.3f}, bore_ymin={bore_ymin:.3f}")

    # --- compute 4 boss X locations (keep original at x0, add 3 to +X) ---
    right_clear = float(bbox.xmax - (boss_r + 3.0))
    if right_clear <= x0 + 3 * (2 * boss_r + 3.0):
        # fallback: still distribute 3 bosses, but with minimum spacing
        right_clear = max(right_clear, x0 + 3 * (2 * boss_r + 3.0))

    span = right_clear - x0
    dx = span / 3.0
    x_positions = [x0 + i * dx for i in range(4)]

    # Only add new bosses (leave the original boss in place)
    tol = 0.25
    new_x_positions = [xp for xp in x_positions if abs(xp - x0) > tol]

    print("Boss pattern x positions (target 4 total):", [round(v, 3) for v in x_positions])
    print("New boss x positions to add:", [round(v, 3) for v in new_x_positions])

    # --- build features with guaranteed overlap so booleans actually fuse ---
    embed = 4.0  # embed into the arm to guarantee intersection
    y_base = y_upper - embed
    boss_h = y_top - y_base
    if boss_h <= 0:
        raise ValueError("Computed boss height is non-positive; check detected planes.")

    res = base

    # Add 3 bosses
    for xp in new_x_positions:
        boss_cyl = (
            cq.Workplane("XZ")
            .workplane(offset=y_base)
            .center(xp, z0)
            .circle(boss_r)
            .extrude(boss_h)
        ).val()

        # Add a small blend-like bulb to mimic a saddle and further ensure overlap
        bulb = cq.Workplane("XY").sphere(boss_r * 1.02).translate((xp, y_upper + 0.25, z0)).val()
        try:
            boss_one = boss_cyl.fuse(bulb)
        except Exception:
            boss_one = boss_cyl

        # Fuse into base
        res = res.fuse(boss_one)

    # Cut bores for the 3 new bosses (blind bore, open at top)
    bore_len = max(0.2, y_top - bore_ymin)
    for xp in new_x_positions:
        bore_cut = (
            cq.Workplane("XZ")
            .workplane(offset=bore_ymin)
            .center(xp, z0)
            .circle(bore_r)
            .extrude(bore_len)
        ).val()
        res = res.cut(bore_cut)

    # --- stability ribs / legs on the sides ---
    # Create gussets on both long side faces (y=y_upper and y=y_lower)
    rib_out = 7.0
    rib_over = 0.6  # overlap into the arm so fuse is robust
    rib_span = max(2.0, boss_r * 0.6)

    def make_rib_at_y(y_plane, direction_sign, xp):
        # direction_sign: +1 extrude +Y, -1 extrude -Y
        xL = max(bbox.xmin + 1.0, xp - (boss_r + rib_span))
        xR = min(bbox.xmax - 1.0, xp + (boss_r + rib_span))

        # Triangle in XZ (height across arm thickness)
        tri = [(xL, z_bottom), (xR, z_bottom), (xp, z_top)]

        start = y_plane - direction_sign * rib_over
        ext = direction_sign * (rib_out + rib_over)

        rib = (
            cq.Workplane("XZ")
            .workplane(offset=start)
            .polyline(tri)
            .close()
            .extrude(ext)
        ).val()
        return rib

    # Add ribs for all 4 boss stations to increase stability across the whole assembly
    for xp in x_positions:
        rib_plus = make_rib_at_y(y_upper, +1, xp)   # on +Y side (boss side)
        rib_minus = make_rib_at_y(y_lower, -1, xp)  # on -Y side (stabilizing leg)
        res = res.fuse(rib_plus)
        res = res.fuse(rib_minus)

    result = cq.Workplane(obj=res)

    # Light edge softening (best-effort)
    try:
        result = result.edges().fillet(0.4)
    except Exception as e:
        print("Fillet failed (non-fatal):", e)

    # Debug: count boss-like cylinders after operation
    try:
        boss_like_x = []
        for f in result.val().Faces():
            if f.geomType() != "CYLINDER":
                continue
            ad = f._geomAdaptor()
            cyl = ad.Cylinder()
            r = float(cyl.Radius())
            d = cyl.Axis().Direction()
            ax = cq.Vector(d.X(), d.Y(), d.Z())
            if _axis_is_y(ax) and (boss_r - 0.4) <= r <= (boss_r + 0.4):
                boss_like_x.append(round(f.Center().x, 2))
        uniq = sorted(set([round(x / 0.5) * 0.5 for x in boss_like_x]))
        print("Post-op approx unique boss-cylinder X positions:", uniq)
        print("Post-op approx boss-cylinder count (unique):", len(uniq))
    except Exception as e:
        print("Post-op cylinder check failed (non-fatal):", e)

    try:
        result = result.clean()
    except Exception:
        pass

    return result
