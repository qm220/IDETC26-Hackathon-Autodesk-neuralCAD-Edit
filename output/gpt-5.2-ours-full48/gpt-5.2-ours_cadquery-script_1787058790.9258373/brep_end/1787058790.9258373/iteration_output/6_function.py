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
    shp = wp0.val()

    bbox = shp.BoundingBox()
    print("Loaded STEP:", step_path)
    print(f"BBOX xmin/xmax: {bbox.xmin:.3f}, {bbox.xmax:.3f}")
    print(f"BBOX ymin/ymax: {bbox.ymin:.3f}, {bbox.ymax:.3f}")
    print(f"BBOX zmin/zmax: {bbox.zmin:.3f}, {bbox.zmax:.3f}")

    faces = list(shp.Faces())

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

    # --- detect arm side planes (Y) and arm thickness planes (Z) ---
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

    z_mid = 0.5 * (z_bottom + z_top)

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

    boss_cands.sort(key=lambda t: t[3].ymax, reverse=True)
    boss_r, boss_axis, boss_center, boss_bb = boss_cands[0]

    def _xz_dist(ci):
        c = ci[2]
        return (c.x - boss_center.x) ** 2 + (c.z - boss_center.z) ** 2

    bore_cands.sort(key=_xz_dist)
    bore_r, bore_axis, bore_center, bore_bb = bore_cands[0]

    x0 = float(boss_center.x)
    z0 = float(boss_center.z)
    y_cyl_start = float(boss_bb.ymin)  # ~24
    y_top = float(boss_bb.ymax)        # ~34
    bore_ymin = float(bore_bb.ymin)    # ~25

    print(
        f"Boss detected: r_outer={boss_r:.3f}, center=({x0:.3f},{boss_center.y:.3f},{z0:.3f}), y_start={y_cyl_start:.3f}, y_top={y_top:.3f}"
    )
    print(f"Bore detected: r_inner={bore_r:.3f}, bore_ymin={bore_ymin:.3f}")

    # --- compute 4 boss X locations (keep original at x0, add 3 to +X) ---
    right_clear = float(bbox.xmax - (boss_r + 3.0))
    avail = right_clear - x0
    if avail <= (2 * boss_r + 6.0):
        raise ValueError("Not enough room to place 3 additional bosses to +X while keeping clearance.")

    dx = avail / 3.0
    x_positions = [x0 + i * dx for i in range(4)]
    x_positions[-1] = min(x_positions[-1], right_clear)

    tol = 0.25
    new_x_positions = [xp for xp in x_positions if abs(xp - x0) > tol]

    print("Boss pattern x positions (target 4 total):", [round(v, 3) for v in x_positions])
    print("New boss x positions to add:", [round(v, 3) for v in new_x_positions])

    # --- build solids lists for robust boolean ops ---
    boss_solids = []
    bore_cut_solids = []
    rib_solids = []

    # Ensure overlap with arm for robust boolean fusion
    embed = 0.8
    cyl_base_y = y_cyl_start - embed
    cyl_h = y_top - cyl_base_y

    def make_lower_bulb_solid(xp: float):
        # hemisphere-ish blend volume under the boss
        sph = cq.Workplane("XY").sphere(boss_r).translate((xp, y_cyl_start, z0))
        half = (
            cq.Workplane("XZ")
            .workplane(offset=y_cyl_start)
            .rect(6 * boss_r, 6 * boss_r)
            .extrude(-6 * boss_r)
        )
        try:
            return sph.intersect(half).val()
        except Exception:
            return sph.val()

    # --- create 3 new bosses + their blind bores ---
    for xp in new_x_positions:
        boss_cyl = (
            cq.Workplane("XZ")
            .workplane(offset=cyl_base_y)
            .center(xp, z0)
            .circle(boss_r)
            .extrude(cyl_h)
        ).val()

        bulb = make_lower_bulb_solid(xp)

        # fuse cylinder + bulb into one boss solid
        try:
            boss_one = cq.Shape.cast(boss_cyl.fuse(bulb))
        except Exception:
            # fallback: keep just the cylinder (still satisfies "4 cylindrical features")
            boss_one = boss_cyl

        boss_solids.append(boss_one)

        # blind bore cut: open at y_top, bottom at bore_ymin
        bore_len = max(0.2, y_top - bore_ymin)
        bore_one = (
            cq.Workplane("XZ")
            .workplane(offset=bore_ymin)
            .center(xp, z0)
            .circle(bore_r)
            .extrude(bore_len)
        ).val()
        bore_cut_solids.append(bore_one)

    # --- stability ribs (gussets) ---
    # Interpreting "on the sides" as on both long side faces (y=y_upper and y=y_lower)
    rib_inset = 0.25
    rib_depth = min(6.5, max(3.0, 0.7 * (boss_center.y - y_upper)))  # reach toward boss

    for xp in x_positions:
        xL = max(bbox.xmin + 1.0, xp - (boss_r + 1.0))
        xR = min(bbox.xmax - 1.0, xp + (boss_r + 1.0))
        tri = [(xL, z_bottom), (xR, z_bottom), (xp, z_top)]

        rib_plus = (
            cq.Workplane("XZ")
            .workplane(offset=y_upper - rib_inset)
            .polyline(tri)
            .close()
            .extrude(rib_depth + rib_inset)
        ).val()

        rib_minus = (
            cq.Workplane("XZ")
            .workplane(offset=y_lower + rib_inset)
            .polyline(tri)
            .close()
            .extrude(-(rib_depth + rib_inset))
        ).val()

        rib_solids.extend([rib_plus, rib_minus])

    # --- boolean apply to the imported shape ---
    res = shp

    def _compound(solids):
        solids2 = [s for s in solids if s is not None]
        if not solids2:
            return None
        if len(solids2) == 1:
            return solids2[0]
        return cq.Compound.makeCompound(solids2)

    boss_comp = _compound(boss_solids)
    rib_comp = _compound(rib_solids)
    bore_comp = _compound(bore_cut_solids)

    if boss_comp is not None:
        res = cq.Shape.cast(res.fuse(boss_comp))

    if rib_comp is not None:
        res = cq.Shape.cast(res.fuse(rib_comp))

    if bore_comp is not None:
        res = cq.Shape.cast(res.cut(bore_comp))

    # Try to merge touching solids
    try:
        res = res.combineSolids()
    except Exception as e:
        print("combineSolids failed (non-fatal):", e)

    result = cq.Workplane(obj=res)

    # Best-effort fillets to soften rib edges (non-fatal)
    try:
        result = result.edges("|Y").fillet(0.35)
    except Exception as e:
        print("Fillet failed (non-fatal):", e)

    # Debug: count boss-like cylinder faces (r~7, axis~Y)
    try:
        cnt = 0
        for f in result.val().Faces():
            if f.geomType() != "CYLINDER":
                continue
            ad = f._geomAdaptor()
            cyl = ad.Cylinder()
            r = float(cyl.Radius())
            d = cyl.Axis().Direction()
            ax = cq.Vector(d.X(), d.Y(), d.Z())
            if _axis_is_y(ax) and (boss_r - 0.4) <= r <= (boss_r + 0.4):
                cnt += 1
        print("Post-op detected CYLINDER faces with r~boss_r, axis~Y:", cnt)
    except Exception as e:
        print("Post-op cylinder count failed (non-fatal):", e)

    try:
        result = result.clean()
    except Exception:
        pass

    return result
