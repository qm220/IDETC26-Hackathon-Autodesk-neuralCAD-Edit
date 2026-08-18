def my_cad_function(args):
    import cadquery as cq
    import os

    input_file = args.get("input_file", None)
    if not input_file:
        raise ValueError("Expected args['input_file']")
    step_path = os.path.expanduser(input_file)
    if not os.path.exists(step_path):
        raise ValueError(f"STEP file not found: {step_path}")

    imp = cq.importers.importStep(step_path)
    wp_in = imp if isinstance(imp, cq.Workplane) else cq.Workplane(obj=imp)
    shp = wp_in.val()

    # --- choose a single base solid (largest by volume) ---
    base_solid = None
    try:
        solids = list(shp.Solids())
    except Exception:
        solids = []

    if solids:
        base_solid = max(solids, key=lambda s: s.Volume())
    else:
        # fall back
        try:
            base_solid = wp_in.solids().val()
        except Exception:
            base_solid = shp

    base = cq.Workplane(obj=base_solid)

    bbox = base_solid.BoundingBox()
    print("Loaded STEP:", step_path)
    print(f"BBOX xmin/xmax: {bbox.xmin:.3f}, {bbox.xmax:.3f}")
    print(f"BBOX ymin/ymax: {bbox.ymin:.3f}, {bbox.ymax:.3f}")
    print(f"BBOX zmin/zmax: {bbox.zmin:.3f}, {bbox.zmax:.3f}")

    faces = list(base_solid.Faces())

    def _safe_normal_at(face):
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

    # --- detect arm side planes (Y) and arm thickness planes (Z) ---
    plane_faces_y = []
    plane_faces_z = []
    for f in faces:
        if f.geomType() != "PLANE":
            continue
        n = _safe_normal_at(f)
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

    z_mid = 0.5 * (z_bottom + z_top)
    print(f"Detected arm side planes y_lower={y_lower:.3f}, y_upper={y_upper:.3f}")
    print(f"Detected arm z planes z_bottom={z_bottom:.3f}, z_top={z_top:.3f}, z_mid={z_mid:.3f}")

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

    def _is_axis_y(ax):
        return abs(ax.y) > 0.92 and abs(ax.x) < 0.35 and abs(ax.z) < 0.35

    boss_candidates = [ci for ci in cyl_info if _is_axis_y(ci[1]) and 6.3 <= ci[0] <= 7.7]
    bore_candidates = [ci for ci in cyl_info if _is_axis_y(ci[1]) and 4.3 <= ci[0] <= 5.7]

    if not boss_candidates:
        raise ValueError("Could not find boss outer cylinder (r~7, axis~Y).")
    if not bore_candidates:
        raise ValueError("Could not find bore cylinder (r~5, axis~Y).")

    boss_candidates.sort(key=lambda t: t[3].ymax, reverse=True)
    boss_r, boss_axis, boss_center, boss_bb = boss_candidates[0]

    def _xz_dist(ci):
        c = ci[2]
        return (c.x - boss_center.x) ** 2 + (c.z - boss_center.z) ** 2

    bore_candidates.sort(key=_xz_dist)
    bore_r, bore_axis, bore_center, bore_bb = bore_candidates[0]

    # original boss extents
    y_cyl_start = float(boss_bb.ymin)  # ~24
    y_top = float(boss_bb.ymax)        # ~34
    bore_ymin = float(bore_bb.ymin)    # ~25

    x0 = float(boss_center.x)
    z0 = float(boss_center.z)

    print(
        f"Boss detected: r_outer={boss_r:.3f}, center=({x0:.3f},{boss_center.y:.3f},{z0:.3f}), y_start={y_cyl_start:.3f}, y_top={y_top:.3f}"
    )
    print(f"Bore detected: r_inner={bore_r:.3f}, bore_ymin={bore_ymin:.3f}")

    # --- compute 4 boss X locations (original + 3 to +X) ---
    right_clear = float(bbox.xmax - (boss_r + 5.0))
    avail = right_clear - x0
    if avail <= 3.0:
        raise ValueError("Not enough room to pattern bosses to the +X direction.")

    dx = avail / 3.0
    x_positions = [x0 + i * dx for i in range(4)]
    x_positions[-1] = min(x_positions[-1], right_clear)
    tol = 0.25
    new_x_positions = [xp for xp in x_positions if abs(xp - x0) > tol]

    print("Boss pattern x positions (target 4 total):", [round(x, 3) for x in x_positions])
    print("New boss x positions to add (excluding original):", [round(x, 3) for x in new_x_positions])

    # --- build additions (new bosses + ribs/legs) and cuts (bores) ---
    add_all = None
    cut_all = None

    # make new bosses intersect the arm robustly
    penetration = 1.8  # push boss into arm so boolean fuse is reliable
    boss_base_y = y_upper - penetration

    # add a small top flange similar to the original ring
    flange_rad = boss_r + 2.0
    flange_thk = 1.0

    for xp in new_x_positions:
        # outer boss
        outer = (
            cq.Workplane("XZ")
            .workplane(offset=boss_base_y)
            .center(xp, z0)
            .circle(boss_r)
            .extrude(y_top - boss_base_y)
        )
        # top flange
        flange = (
            cq.Workplane("XZ")
            .workplane(offset=y_top - flange_thk)
            .center(xp, z0)
            .circle(flange_rad)
            .extrude(flange_thk)
        )
        boss_solid = outer.union(flange)

        add_all = boss_solid if add_all is None else add_all.union(boss_solid)

        # blind bore cut (do not cut into arm)
        bore_start = bore_ymin
        bore_len = max(0.2, y_top - bore_start)
        bore = (
            cq.Workplane("XZ")
            .workplane(offset=bore_start)
            .center(xp, z0)
            .circle(bore_r)
            .extrude(bore_len)
        )
        cut_all = bore if cut_all is None else cut_all.union(bore)

    # --- stability ribs/legs on both side faces for each boss location (including original) ---
    rib_run = max(10.0, 1.6 * boss_r)   # how far ribs extend along X from the boss
    rib_tip_inset = max(1.5, 0.35 * boss_r)

    # +Y gussets: from slightly inside arm to well into boss region
    y_plus_start = y_upper - 0.25
    y_plus_len = (y_top - y_plus_start) + 0.25

    # -Y legs: simple outward feet from the opposite side
    y_minus_start = y_lower + 0.25
    leg_len = 8.0

    def _xz_triangle(base_x, tip_x, z0a, z0b, z_tip):
        # triangle points in XZ
        return [(base_x, z0a), (base_x, z0b), (tip_x, z_tip)]

    ribs_all = None
    for xp in x_positions:
        # left and right gussets on +Y side
        base_xL = xp - (boss_r + rib_run)
        tip_xL = xp - rib_tip_inset
        base_xR = xp + (boss_r + rib_run)
        tip_xR = xp + rib_tip_inset

        triL = _xz_triangle(base_xL, tip_xL, z_bottom, z_top, z_mid)
        triR = _xz_triangle(base_xR, tip_xR, z_bottom, z_top, z_mid)

        gus_plus_L = (
            cq.Workplane("XZ").workplane(offset=y_plus_start)
            .polyline(triL).close()
            .extrude(y_plus_len)
        )
        gus_plus_R = (
            cq.Workplane("XZ").workplane(offset=y_plus_start)
            .polyline(triR).close()
            .extrude(y_plus_len)
        )

        # left and right feet on -Y side
        gus_minus_L = (
            cq.Workplane("XZ").workplane(offset=y_minus_start)
            .polyline(triL).close()
            .extrude(-leg_len)
        )
        gus_minus_R = (
            cq.Workplane("XZ").workplane(offset=y_minus_start)
            .polyline(triR).close()
            .extrude(-leg_len)
        )

        pair = gus_plus_L.union(gus_plus_R).union(gus_minus_L).union(gus_minus_R)
        ribs_all = pair if ribs_all is None else ribs_all.union(pair)

    if ribs_all is not None:
        add_all = ribs_all if add_all is None else add_all.union(ribs_all)

    # --- apply booleans to base ---
    result = base
    if add_all is not None:
        result = result.union(add_all, clean=True)
    if cut_all is not None:
        result = result.cut(cut_all)

    # Best-effort softening (optional)
    try:
        result = result.edges("|Y").fillet(0.4)
    except Exception as e:
        print("Fillet failed (non-fatal):", e)

    try:
        result = result.clean()
    except Exception:
        pass

    return result
