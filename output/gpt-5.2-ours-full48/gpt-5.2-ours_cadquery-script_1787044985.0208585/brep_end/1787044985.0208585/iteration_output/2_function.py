def my_cad_function(args):
    import cadquery as cq
    import os

    input_file = os.path.expanduser(args.get("input_file", ""))
    wp_in = cq.importers.importStep(input_file)

    # Normalize to a Workplane holding a single top-level shape
    if isinstance(wp_in, cq.Workplane):
        top_shape = wp_in.val()
        wp_all = cq.Workplane("XY").newObject([top_shape])
    else:
        top_shape = wp_in
        wp_all = cq.Workplane("XY").newObject([top_shape])

    top_bb = top_shape.BoundingBox()
    solids = wp_all.solids().vals()

    print(f"Loaded STEP. Solids found: {len(solids)}")
    print(f"Overall bbox lens (x,y,z): ({top_bb.xlen:.2f}, {top_bb.ylen:.2f}, {top_bb.zlen:.2f})")

    if not solids:
        print("No solids found; returning original")
        return wp_all

    axis_names = ["X", "Y", "Z"]

    def bb_center(bb, ai):
        c = bb.center
        return [c.x, c.y, c.z][ai]

    def bb_min(bb, ai):
        return [bb.xmin, bb.ymin, bb.zmin][ai]

    def bb_max(bb, ai):
        return [bb.xmax, bb.ymax, bb.zmax][ai]

    # 1) Infer front axis/sign from the faceplate-like thin plate
    plate_candidates = []
    for i, s in enumerate(solids):
        bb = s.BoundingBox()
        dims = [bb.xlen, bb.ylen, bb.zlen]
        dims_sorted = sorted(dims)
        min_d, mid_d, max_d = dims_sorted[0], dims_sorted[1], dims_sorted[2]
        if min_d < 8.0 and mid_d > 150.0 and max_d > 150.0:
            score = (mid_d * max_d) / max(min_d, 1e-6)
            plate_candidates.append((score, i, s, bb, dims))

    plate_idx = None
    front_axis_i = 2
    front_sign = 1

    if plate_candidates:
        plate_candidates.sort(key=lambda t: t[0], reverse=True)
        _, plate_idx, _, plate_bb, plate_dims = plate_candidates[0]
        front_axis_i = min(range(3), key=lambda k: plate_dims[k])
        overall_c = bb_center(top_bb, front_axis_i)
        plate_c = bb_center(plate_bb, front_axis_i)
        front_sign = 1 if plate_c >= overall_c else -1
        print(
            f"Faceplate-like solid idx={plate_idx}, dims={tuple(round(d,2) for d in plate_dims)} -> "
            f"front axis={axis_names[front_axis_i]}, front_sign={'+' if front_sign>0 else '-'}"
        )
    else:
        print("WARNING: Could not detect faceplate plate. Falling back to front axis=Z, front_sign=+")

    # 2) Pick a front-protruding handle/lever (aligned with front axis, on front side)
    top_lens = [top_bb.xlen, top_bb.ylen, top_bb.zlen]
    front_len = max(top_lens[front_axis_i], 1e-6)

    # up axis = largest remaining axis
    up_axis_i = max([k for k in range(3) if k != front_axis_i], key=lambda k: top_lens[k])
    lat_axis_i = [k for k in range(3) if k not in (front_axis_i, up_axis_i)][0]

    print(f"Using axes: up={axis_names[up_axis_i]}, front={axis_names[front_axis_i]}, lateral={axis_names[lat_axis_i]}")

    overall_lat_center = [top_bb.center.x, top_bb.center.y, top_bb.center.z][lat_axis_i]
    up_len = max(top_lens[up_axis_i], 1e-6)
    lat_len = max(top_lens[lat_axis_i], 1e-6)

    handle_candidates = []
    for i, s in enumerate(solids):
        if i == plate_idx:
            continue
        bb = s.BoundingBox()
        dims = [bb.xlen, bb.ylen, bb.zlen]
        principal = max(range(3), key=lambda k: dims[k])
        if principal != front_axis_i:
            continue

        length = dims[principal]
        cross = [dims[k] for k in range(3) if k != principal]
        cross_min = min(cross)
        cross_max = max(cross)
        slender = length / max(cross_min, 1e-6)

        if length < 60.0 or length > 350.0:
            continue
        if cross_min < 6.0:
            continue
        if cross_max > 140.0:
            continue
        if slender < 2.0:
            continue

        fc = bb_center(bb, front_axis_i)
        if front_sign > 0:
            front_norm = (fc - bb_min(top_bb, front_axis_i)) / front_len
        else:
            front_norm = (bb_max(top_bb, front_axis_i) - fc) / front_len
        if front_norm < 0.50:
            continue

        uc = bb_center(bb, up_axis_i)
        up_norm = (uc - bb_min(top_bb, up_axis_i)) / up_len

        lc = bb_center(bb, lat_axis_i)
        lat_norm = abs(lc - overall_lat_center) / lat_len

        score = (
            12.0 * front_norm
            + 2.5 * up_norm
            + 0.03 * length
            + 0.4 * slender
            - 2.0 * lat_norm
        )
        handle_candidates.append((score, i, s, bb, dims, length, cross_min, cross_max, slender, front_norm))

    if not handle_candidates:
        print("ERROR: Could not find a suitable front-protruding handle/lever candidate. Returning original.")
        return wp_all

    handle_candidates.sort(key=lambda t: t[0], reverse=True)
    score, handle_idx, handle_solid, handle_bb, handle_dims, length, *_ = handle_candidates[0]
    print(
        f"Selected lever/handle solid idx={handle_idx}, score={score:.3f}, dims={tuple(round(d,2) for d in handle_dims)}, "
        f"length={length:.2f}"
    )

    # 3) Extend by EXACTLY 50mm from the current front-most tip.
    ext_len = 50.0  # mm

    dir_vec = [cq.Vector(1, 0, 0), cq.Vector(0, 1, 0), cq.Vector(0, 0, 1)][front_axis_i].multiply(front_sign)
    sel = (">" if front_sign > 0 else "<") + axis_names[front_axis_i]

    # Estimate radius from the two cross-section bbox dims
    cross_axes = [k for k in range(3) if k != front_axis_i]
    r_est = 0.25 * (handle_dims[cross_axes[0]] + handle_dims[cross_axes[1]])
    r_est = max(2.0, min(r_est, 80.0))

    hw = cq.Workplane("XY").newObject([handle_solid])
    tip_vertices = hw.vertices(sel).vals()
    if tip_vertices:
        pts = [v.Center() for v in tip_vertices]
        tip = cq.Vector(
            sum(p.x for p in pts) / len(pts),
            sum(p.y for p in pts) / len(pts),
            sum(p.z for p in pts) / len(pts),
        )
    else:
        c = handle_bb.center
        tip = cq.Vector(c.x, c.y, c.z)
        if front_axis_i == 0:
            tip.x = handle_bb.xmax if front_sign > 0 else handle_bb.xmin
        elif front_axis_i == 1:
            tip.y = handle_bb.ymax if front_sign > 0 else handle_bb.ymin
        else:
            tip.z = handle_bb.zmax if front_sign > 0 else handle_bb.zmin

    # Build an extension that increases the extreme by ext_len (not ext_len + radius)
    # Use a cylinder + spherical cap, with the sphere center positioned so its farthest point is exactly ext_len.
    overlap = min(2.0, 0.15 * r_est)  # small overlap to guarantee boolean fusion

    # If ext_len is smaller than the radius, just place the sphere so its farthest point is ext_len.
    sphere_center = tip.add(dir_vec.multiply(ext_len - r_est))

    cyl_len = max(0.0, (ext_len - r_est) + overlap)
    cyl_start = tip.add(dir_vec.multiply(-overlap))

    print(f"Tip approx=({tip.x:.3f},{tip.y:.3f},{tip.z:.3f}), r_est={r_est:.2f}")
    print(
        f"Requested extension: {ext_len:.2f}mm along {axis_names[front_axis_i]}{'+' if front_sign>0 else '-'}; "
        f"cyl_len={cyl_len:.2f}, overlap={overlap:.2f}"
    )

    ext_shapes = []
    if cyl_len > 1e-6:
        ext_shapes.append(cq.Solid.makeCylinder(r_est, cyl_len, cyl_start, dir_vec))
    ext_shapes.append(cq.Solid.makeSphere(r_est, sphere_center))

    result = wp_all
    for sh in ext_shapes:
        result = result.union(sh)

    return result
