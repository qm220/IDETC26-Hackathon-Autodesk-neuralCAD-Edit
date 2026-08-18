def my_cad_function(args):
    import cadquery as cq
    import os, math

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

    # Helper to access axis values
    def bb_len(bb, ai):
        return [bb.xlen, bb.ylen, bb.zlen][ai]

    def bb_min(bb, ai):
        return [bb.xmin, bb.ymin, bb.zmin][ai]

    def bb_max(bb, ai):
        return [bb.xmax, bb.ymax, bb.zmax][ai]

    def bb_center(bb, ai):
        c = bb.center
        return [c.x, c.y, c.z][ai]

    axis_names = ["X", "Y", "Z"]

    # 1) Infer "front-back" axis by finding the big faceplate-like thin plate solid
    plate_candidates = []
    for i, s in enumerate(solids):
        bb = s.BoundingBox()
        dims = [bb.xlen, bb.ylen, bb.zlen]
        dims_sorted = sorted(dims)
        min_d, mid_d, max_d = dims_sorted[0], dims_sorted[1], dims_sorted[2]
        # thin plate: one small thickness, two large spans
        if min_d < 8.0 and mid_d > 150.0 and max_d > 150.0:
            # score prefers larger plate and thinner thickness
            score = (mid_d * max_d) / max(min_d, 1e-6)
            plate_candidates.append((score, i, s, bb, dims))

    plate_idx = None
    front_axis_i = 2  # fallback Z
    front_sign = 1

    if plate_candidates:
        plate_candidates.sort(key=lambda t: t[0], reverse=True)
        pscore, plate_idx, plate_solid, plate_bb, plate_dims = plate_candidates[0]
        # front axis is the plate thickness axis
        front_axis_i = min(range(3), key=lambda k: plate_dims[k])

        # decide which direction (+/-) is "front": faceplate should sit on the front side
        overall_center = top_bb.center
        overall_c = [overall_center.x, overall_center.y, overall_center.z][front_axis_i]
        plate_c = bb_center(plate_bb, front_axis_i)
        front_sign = 1 if plate_c >= overall_c else -1

        print(
            f"Faceplate-like solid idx={plate_idx}, dims={tuple(round(d,2) for d in plate_dims)} -> "
            f"front axis={axis_names[front_axis_i]}, front_sign={'+' if front_sign>0 else '-'}"
        )
    else:
        # If we couldn't detect the faceplate, assume front-back is Z and front is +Z
        print("WARNING: Could not detect faceplate plate. Falling back to front axis=Z, front_sign=+")
        front_axis_i = 2
        front_sign = 1

    # 2) Infer "up" axis as the overall largest dimension axis, but not equal to front axis
    overall_lens = [top_bb.xlen, top_bb.ylen, top_bb.zlen]
    up_axis_i = max(range(3), key=lambda k: overall_lens[k])
    if up_axis_i == front_axis_i:
        # take next largest
        remaining = [k for k in range(3) if k != front_axis_i]
        up_axis_i = max(remaining, key=lambda k: overall_lens[k])

    lat_axis_i = [k for k in range(3) if k not in (front_axis_i, up_axis_i)][0]

    print(f"Using axes: up={axis_names[up_axis_i]}, front={axis_names[front_axis_i]}, lateral={axis_names[lat_axis_i]}")

    # 3) Find protruding "lever/handle" candidate aligned with the front axis and near the front
    front_len = max(bb_len(top_bb, front_axis_i), 1e-6)
    up_len = max(bb_len(top_bb, up_axis_i), 1e-6)
    lat_len = max(bb_len(top_bb, lat_axis_i), 1e-6)

    overall_lat_center = [top_bb.center.x, top_bb.center.y, top_bb.center.z][lat_axis_i]

    handle_candidates = []
    for i, s in enumerate(solids):
        if i == plate_idx:
            continue
        bb = s.BoundingBox()
        dims = [bb.xlen, bb.ylen, bb.zlen]
        principal = max(range(3), key=lambda k: dims[k])

        # must mainly run along the inferred front axis
        if principal != front_axis_i:
            continue

        length = dims[principal]
        cross = [dims[k] for k in range(3) if k != principal]
        cross_min = min(cross)
        cross_max = max(cross)
        slender = length / max(cross_min, 1e-6)

        # Filter out vent slats / tiny rods / huge housings
        if length < 60.0 or length > 350.0:
            continue
        if cross_min < 6.0:
            continue
        if cross_max > 140.0:
            continue
        if slender < 2.0:
            continue

        # position preference: nearer front and upper-mid height; centered laterally
        fc = bb_center(bb, front_axis_i)
        if front_sign > 0:
            front_norm = (fc - bb_min(top_bb, front_axis_i)) / front_len
        else:
            front_norm = (bb_max(top_bb, front_axis_i) - fc) / front_len

        uc = bb_center(bb, up_axis_i)
        up_norm = (uc - bb_min(top_bb, up_axis_i)) / up_len

        lc = bb_center(bb, lat_axis_i)
        lat_norm = abs(lc - overall_lat_center) / lat_len

        # Must be on/near the front half of the machine
        if front_norm < 0.50:
            continue

        score = (
            12.0 * front_norm
            + 2.5 * up_norm
            + 0.03 * length
            + 0.4 * slender
            - 2.0 * lat_norm
        )

        handle_candidates.append((score, i, s, bb, dims, length, cross_min, cross_max, slender, front_norm, up_norm, lat_norm))

    if not handle_candidates:
        print("ERROR: Could not find a suitable front-protruding handle/lever candidate. Returning original.")
        return wp_all

    handle_candidates.sort(key=lambda t: t[0], reverse=True)
    (score, handle_idx, handle_solid, handle_bb, handle_dims, length, cross_min, cross_max, slender, front_norm, up_norm, lat_norm) = handle_candidates[0]

    print(
        f"Selected lever/handle solid idx={handle_idx}, score={score:.3f}, dims={tuple(round(d,2) for d in handle_dims)}, "
        f"length={length:.2f}, cross_min={cross_min:.2f}, slender={slender:.2f}, front_norm={front_norm:.2f}"
    )

    # 4) Build a 50mm extension on the OUTER (front-most) end.
    ext_len = 50.0  # mm

    # Direction vector along front axis
    dir_vec = [cq.Vector(1,0,0), cq.Vector(0,1,0), cq.Vector(0,0,1)][front_axis_i].multiply(front_sign)

    # Determine extreme selector string for front-most end
    sel = (">" if front_sign > 0 else "<") + axis_names[front_axis_i]

    # Estimate radius from cross-section of handle bbox
    # (avg diameter)/2 = (cross0+cross1)/4
    cross_axes = [k for k in range(3) if k != front_axis_i]
    r_est = 0.25 * (handle_dims[cross_axes[0]] + handle_dims[cross_axes[1]])
    r_est = max(2.0, min(r_est, 80.0))

    # Find tip point using extreme vertices (more robust for rounded tips)
    hw = cq.Workplane("XY").newObject([handle_solid])
    tip_vertices = hw.vertices(sel).vals()
    if tip_vertices:
        pts = [v.Center() for v in tip_vertices]
        tip = cq.Vector(
            sum(p.x for p in pts) / len(pts),
            sum(p.y for p in pts) / len(pts),
            sum(p.z for p in pts) / len(pts),
        )
        print(f"Tip vertices found: {len(pts)}; tip approx=({tip.x:.3f},{tip.y:.3f},{tip.z:.3f})")
    else:
        # fallback to bbox extreme center
        c = handle_bb.center
        tip = cq.Vector(c.x, c.y, c.z)
        if front_axis_i == 0:
            tip.x = handle_bb.xmax if front_sign > 0 else handle_bb.xmin
        elif front_axis_i == 1:
            tip.y = handle_bb.ymax if front_sign > 0 else handle_bb.ymin
        else:
            tip.z = handle_bb.zmax if front_sign > 0 else handle_bb.zmin
        print(f"No tip vertices at extreme; using bbox tip=({tip.x:.3f},{tip.y:.3f},{tip.z:.3f})")

    # Start the new extension slightly inside the existing tip to ensure boolean fusion.
    # Approximate that the rounded cap radius is ~r_est.
    start_pt = tip.add(dir_vec.multiply(-r_est))
    cyl_len = ext_len + r_est
    new_tip_center = tip.add(dir_vec.multiply(ext_len))

    print(f"Extending by {ext_len}mm along {axis_names[front_axis_i]}{'+' if front_sign>0 else '-'}; r_est={r_est:.2f}")
    print(f"Extension start=({start_pt.x:.3f},{start_pt.y:.3f},{start_pt.z:.3f}), cyl_len={cyl_len:.2f}, new_tip_center=({new_tip_center.x:.3f},{new_tip_center.y:.3f},{new_tip_center.z:.3f})")

    ext_cyl = cq.Solid.makeCylinder(r_est, cyl_len, start_pt, dir_vec)
    ext_sph = cq.Solid.makeSphere(r_est, new_tip_center)

    result = wp_all.union(ext_cyl).union(ext_sph)
    return result
