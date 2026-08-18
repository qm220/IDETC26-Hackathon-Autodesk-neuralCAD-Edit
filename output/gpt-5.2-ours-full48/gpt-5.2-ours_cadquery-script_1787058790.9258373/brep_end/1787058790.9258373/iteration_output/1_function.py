def my_cad_function(args):
    import cadquery as cq
    import os

    input_file = args.get("input_file", None)
    if not input_file or not os.path.exists(os.path.expanduser(input_file)):
        raise ValueError("Expected args['input_file'] to be a valid STEP path")
    step_path = os.path.expanduser(input_file)

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

    # --- Detect main arm planes (y-sides and z top/bottom) ---
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

    boss_candidates.sort(key=lambda t: t[3].ymax, reverse=True)
    boss_r, boss_axis, boss_center, boss_bb, _ = boss_candidates[0]

    if not bore_candidates:
        raise ValueError("Could not find bore cylinder (r~5, axis~Y).")

    # pick bore closest to boss in XZ
    def _xz_dist(ci):
        c = ci[2]
        return (c.x - boss_center.x) ** 2 + (c.z - boss_center.z) ** 2

    bore_candidates.sort(key=_xz_dist)
    bore_r, bore_axis, bore_center, bore_bb, _ = bore_candidates[0]

    # Use measured y extents for better alignment
    y_cyl_start = float(boss_bb.ymin)  # ~24
    y_top = float(boss_bb.ymax)        # ~34
    boss_len = y_top - y_cyl_start

    bore_ymin = float(bore_bb.ymin)    # ~25
    bore_depth = float(bore_bb.ymax - bore_bb.ymin)  # ~9

    x0 = float(boss_center.x)
    z0 = float(boss_center.z)

    print(f"Boss detected: r_outer={boss_r:.3f}, center=({x0:.3f},{boss_center.y:.3f},{z0:.3f}), y_start={y_cyl_start:.3f}, y_top={y_top:.3f}")
    print(f"Bore detected: r_inner={bore_r:.3f}, bore_ymin={bore_ymin:.3f}, bore_depth={bore_depth:.3f}")

    # --- Determine 4 boss x positions (keep original + add 3), prefer to the +X side ---
    margin_right = boss_r + 3.0
    min_dx = 2.0 * boss_r + 6.0
    avail_to_right = (bbox.xmax - margin_right) - x0

    if avail_to_right >= 3 * min_dx:
        dx = avail_to_right / 3.0
        x_positions = [x0 + i * dx for i in range(4)]
    else:
        # fallback: distribute across usable arm span
        margin_left = boss_r + 5.0
        usable_min = bbox.xmin + margin_left
        usable_max = bbox.xmax - margin_right
        if usable_max <= usable_min:
            usable_min = bbox.xmin + 0.25 * (bbox.xmax - bbox.xmin)
            usable_max = bbox.xmax - 0.1 * (bbox.xmax - bbox.xmin)
        x_positions = [usable_min + (usable_max - usable_min) * i / 3.0 for i in range(4)]

    tol = 0.25
    new_x_positions = [xp for xp in x_positions if abs(xp - x0) > tol]

    print("Boss pattern x positions (target 4 total):", [round(x, 3) for x in x_positions])
    print("New boss x positions to add (excluding original):", [round(x, 3) for x in new_x_positions])

    result = wp

    # --- Add 3 new bosses with robust overlap into arm for a true fuse ---
    overlap_into_arm = min(1.0, max(0.5, 0.5 * (y_cyl_start - y_upper + 1.0)))
    overlap_into_arm = max(0.6, overlap_into_arm)
    foot_extra = 2.0
    foot_y0 = float(y_upper - overlap_into_arm)  # start slightly inside arm
    foot_y1 = float(y_cyl_start)                 # meet cylinder start
    # ensure positive height for loft
    if foot_y1 <= foot_y0 + 0.05:
        foot_y1 = foot_y0 + 0.8

    for xp in new_x_positions:
        # main cylinder (starts slightly inside arm to guarantee intersection)
        cyl_start = y_cyl_start - overlap_into_arm
        cyl_len_eff = y_top - cyl_start
        outer_cyl = (
            cq.Workplane("XZ")
            .workplane(offset=cyl_start)
            .center(xp, z0)
            .circle(boss_r)
            .extrude(cyl_len_eff)
        )

        # frustum-like foot (approximates saddle) from a slightly larger radius at arm side to boss radius
        foot = (
            cq.Workplane("XZ")
            .workplane(offset=foot_y0)
            .center(xp, z0)
            .circle(boss_r + foot_extra)
            .workplane(offset=(foot_y1 - foot_y0))
            .circle(boss_r)
            .loft(combine=True)
        )

        boss_solid = outer_cyl.union(foot)
        result = result.union(boss_solid)

        # blind bore (keep it starting above the arm side, like original)
        bore_start = max(bore_ymin, y_cyl_start + 0.5)
        bore_depth_eff = min(bore_depth, y_top - bore_start)
        if bore_depth_eff > 0.25:
            bore_cut = (
                cq.Workplane("XZ")
                .workplane(offset=bore_start)
                .center(xp, z0)
                .circle(bore_r)
                .extrude(bore_depth_eff)
            )
            result = result.cut(bore_cut)

    # --- Add stability ribs/legs on the sides (ensure overlap so they fuse to the arm/bosses) ---
    # We create small gussets on both side faces (y=y_upper and y=y_lower) for each boss position.
    rib_len = max(6.0, 1.6 * boss_r)
    rib_ext = max(6.0, min(0.85 * boss_len, boss_len + 2.0))
    rib_overlap = 0.8  # overlap into arm to avoid mere face-touching compounds

    def _rib_pair_at(xp, y_base, extrude_dir):
        # Put the near-boss point slightly *inside* the boss radius to guarantee intersection.
        near = boss_r - 0.6
        far = boss_r + rib_len

        left = (
            cq.Workplane("XZ")
            .workplane(offset=y_base)
            .polyline([
                (xp - near, z_mid),
                (xp - far, z_bottom),
                (xp - far, z_top),
            ])
            .close()
            .extrude(extrude_dir * (rib_ext + rib_overlap))
        )

        right = (
            cq.Workplane("XZ")
            .workplane(offset=y_base)
            .polyline([
                (xp + near, z_mid),
                (xp + far, z_bottom),
                (xp + far, z_top),
            ])
            .close()
            .extrude(extrude_dir * (rib_ext + rib_overlap))
        )
        return left.union(right)

    # +Y side (boss side): start slightly inside arm and extrude outward +Y
    ribs_plus = None
    y_base_plus = y_upper - rib_overlap
    for xp in x_positions:
        rp = _rib_pair_at(xp, y_base_plus, +1)
        ribs_plus = rp if ribs_plus is None else ribs_plus.union(rp)
    result = result.union(ribs_plus)

    # -Y side: create outward ribs/"legs" for stability (wider stance), also overlapped into arm
    ribs_minus = None
    y_base_minus = y_lower + rib_overlap
    for xp in x_positions:
        rm = _rib_pair_at(xp, y_base_minus, -1)
        ribs_minus = rm if ribs_minus is None else ribs_minus.union(rm)
    result = result.union(ribs_minus)

    # Best-effort small fillet to soften sharp rib edges (avoid heavy global filleting)
    try:
        # mostly affects rib prism edges; keep small to reduce failure risk
        result = result.edges("|X").fillet(0.4)
    except Exception as e:
        print("Fillet attempt failed (non-fatal):", e)

    return result
