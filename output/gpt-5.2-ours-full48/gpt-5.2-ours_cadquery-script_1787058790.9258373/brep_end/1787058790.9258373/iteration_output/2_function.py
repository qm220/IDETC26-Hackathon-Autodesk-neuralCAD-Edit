def my_cad_function(args):
    import cadquery as cq
    import os

    input_file = args.get("input_file", None)
    if not input_file:
        raise ValueError("Expected args['input_file']")
    step_path = os.path.expanduser(input_file)
    if not os.path.exists(step_path):
        raise ValueError(f"STEP file not found: {step_path}")

    model = cq.importers.importStep(step_path)
    wp = model if hasattr(model, "val") else cq.Workplane(obj=model)
    shape = wp.val()

    bbox = shape.BoundingBox()
    print("Loaded STEP:", step_path)
    print(f"BBOX xmin/xmax: {bbox.xmin:.3f}, {bbox.xmax:.3f}")
    print(f"BBOX ymin/ymax: {bbox.ymin:.3f}, {bbox.ymax:.3f}")
    print(f"BBOX zmin/zmax: {bbox.zmin:.3f}, {bbox.zmax:.3f}")
    print("Faces:", len(shape.Faces()), "Edges:", len(shape.Edges()))

    faces = list(shape.Faces())

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

    # --- Detect arm side planes in Y and arm thickness planes in Z ---
    plane_faces_y = []
    plane_faces_z = []
    for f in faces:
        if f.geomType() != "PLANE":
            continue
        n = _safe_normal_at(f)
        c = f.Center()
        a = f.Area()
        if abs(n.y) > 0.95 and abs(n.x) < 0.25 and abs(n.z) < 0.25:
            plane_faces_y.append((a, c.y, f))
        if abs(n.z) > 0.95 and abs(n.x) < 0.25 and abs(n.y) < 0.25:
            plane_faces_z.append((a, c.z, f))

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

    # --- Detect boss + bore cylinders (axis ~Y) ---
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
            cyl_info.append((r, axis, c, bb, f))
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

    # choose boss with highest ymax (top of socket)
    boss_candidates.sort(key=lambda t: t[3].ymax, reverse=True)
    boss_r, boss_axis, boss_center, boss_bb, _ = boss_candidates[0]

    # pick bore closest to boss in XZ
    def _xz_dist(ci):
        c = ci[2]
        return (c.x - boss_center.x) ** 2 + (c.z - boss_center.z) ** 2

    bore_candidates.sort(key=_xz_dist)
    bore_r, bore_axis, bore_center, bore_bb, _ = bore_candidates[0]

    # extents
    y_cyl_start = float(boss_bb.ymin)  # ~24
    y_top = float(boss_bb.ymax)        # ~34
    boss_len = y_top - y_cyl_start

    bore_ymin = float(bore_bb.ymin)    # ~25
    bore_depth = float(bore_bb.ymax - bore_bb.ymin)  # ~9

    x0 = float(boss_center.x)
    z0 = float(boss_center.z)

    print(
        f"Boss detected: r_outer={boss_r:.3f}, center=({x0:.3f},{boss_center.y:.3f},{z0:.3f}), y_start={y_cyl_start:.3f}, y_top={y_top:.3f}"
    )
    print(f"Bore detected: r_inner={bore_r:.3f}, bore_ymin={bore_ymin:.3f}, bore_depth={bore_depth:.3f}")

    # --- Compute 4 boss X locations (keep original at x0, add 3 to +X) ---
    # Keep clear of right end and maintain reasonable spacing
    right_clear = float(bbox.xmax - (boss_r + 5.0))
    avail = right_clear - x0
    if avail <= 3.0:
        raise ValueError("Not enough room to pattern bosses to the +X direction.")

    dx = avail / 3.0
    x_positions = [x0 + i * dx for i in range(4)]

    # Clamp last just in case numeric issues
    x_positions[-1] = min(x_positions[-1], right_clear)

    # exclude original (within tol)
    tol = 0.25
    new_x_positions = [xp for xp in x_positions if abs(xp - x0) > tol]

    print("Boss pattern x positions (target 4 total):", [round(x, 3) for x in x_positions])
    print("New boss x positions to add (excluding original):", [round(x, 3) for x in new_x_positions])

    result = wp

    # --- Build additions first (then union) ---
    add_solid = None
    cut_solid = None

    # Force overlap of new bosses into arm so boolean union produces one connected solid
    # Need cyl_start <= y_upper - eps
    eps_in = 0.2
    required_overlap = max(1.2, (y_cyl_start - y_upper) + 0.8)  # ensures penetration into the arm

    base_pad_extra_r = 2.0

    for xp in new_x_positions:
        cyl_start = y_cyl_start - required_overlap
        cyl_start = min(cyl_start, y_upper - eps_in)
        cyl_len_eff = y_top - cyl_start
        if cyl_len_eff <= 0.5:
            continue

        outer_cyl = (
            cq.Workplane("XZ")
            .workplane(offset=cyl_start)
            .center(xp, z0)
            .circle(boss_r)
            .extrude(cyl_len_eff)
        )

        # a short larger-radius pad starting slightly inside the arm to guarantee fusion + suggest a saddle blend
        pad_start = y_upper - eps_in
        pad_end = min(y_cyl_start + 0.2, y_top - 0.2)
        pad_h = pad_end - pad_start
        if pad_h > 0.25:
            pad = (
                cq.Workplane("XZ")
                .workplane(offset=pad_start)
                .center(xp, z0)
                .circle(boss_r + base_pad_extra_r)
                .extrude(pad_h)
            )
            boss_solid = outer_cyl.union(pad)
        else:
            boss_solid = outer_cyl

        add_solid = boss_solid if add_solid is None else add_solid.union(boss_solid)

        # blind bore (start above arm, like original)
        bore_start = max(bore_ymin, y_cyl_start + 0.8)
        bore_depth_eff = min(bore_depth, y_top - bore_start)
        if bore_depth_eff > 0.25:
            bore_cut = (
                cq.Workplane("XZ")
                .workplane(offset=bore_start)
                .center(xp, z0)
                .circle(bore_r)
                .extrude(bore_depth_eff)
            )
            cut_solid = bore_cut if cut_solid is None else cut_solid.union(bore_cut)

    # --- Stability ribs/legs on side faces (for ALL 4 bosses) ---
    rib_len = max(7.0, 1.15 * boss_r)

    # +Y ribs: extend from within arm to well into the boss region
    y_base_plus = y_upper - 0.3
    rib_y_plus = max(8.0, (y_top - y_base_plus) - 0.3)

    # -Y legs: extend outward to widen stance
    y_base_minus = y_lower + 0.3
    rib_y_minus = max(8.0, min(14.0, 0.8 * (y_upper - y_lower) + 8.0))

    def _rib_pair(xp, y_base, y_dir, rib_y_len):
        # rib touches near boss footprint in X, spans full Z thickness
        near = max(0.8, boss_r * 0.65)
        x_in_l = xp - near
        x_out_l = xp - (boss_r + rib_len)
        x_in_r = xp + near
        x_out_r = xp + (boss_r + rib_len)

        left = (
            cq.Workplane("XZ")
            .workplane(offset=y_base)
            .polyline([
                (x_in_l, z_mid),
                (x_out_l, z_bottom),
                (x_out_l, z_top),
            ])
            .close()
            .extrude(y_dir * rib_y_len)
        )
        right = (
            cq.Workplane("XZ")
            .workplane(offset=y_base)
            .polyline([
                (x_in_r, z_mid),
                (x_out_r, z_bottom),
                (x_out_r, z_top),
            ])
            .close()
            .extrude(y_dir * rib_y_len)
        )
        return left.union(right)

    ribs = None
    for xp in x_positions:
        rp = _rib_pair(xp, y_base_plus, +1, rib_y_plus)
        rm = _rib_pair(xp, y_base_minus, -1, rib_y_minus)
        pair = rp.union(rm)
        ribs = pair if ribs is None else ribs.union(pair)

    add_solid = ribs if add_solid is None else add_solid.union(ribs)

    # --- Apply booleans ---
    if add_solid is not None:
        result = result.union(add_solid)
    if cut_solid is not None:
        result = result.cut(cut_solid)

    # Try to reduce to a single solid if everything is connected
    try:
        result = result.combineSolids()
    except Exception as e:
        print("combineSolids failed (non-fatal):", e)

    # Small fillet as a best-effort softening on long rib edges
    try:
        result = result.edges("|Y").fillet(0.35)
    except Exception as e:
        print("Fillet attempt failed (non-fatal):", e)

    return result
