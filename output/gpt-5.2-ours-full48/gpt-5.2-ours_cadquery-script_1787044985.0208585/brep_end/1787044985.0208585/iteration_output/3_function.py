def my_cad_function(args):
    import cadquery as cq
    import os
    import math

    input_file = os.path.expanduser(args.get("input_file", ""))
    wp_in = cq.importers.importStep(input_file)

    # Normalize to a Workplane holding a single top-level shape
    if isinstance(wp_in, cq.Workplane):
        top_shape = wp_in.val()
        wp_all = cq.Workplane("XY").newObject([top_shape])
    else:
        top_shape = wp_in
        wp_all = cq.Workplane("XY").newObject([top_shape])

    solids = wp_all.solids().vals()
    top_bb = top_shape.BoundingBox()

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

    # 1) Infer front axis/sign from a faceplate-like thin plate (very thin in one axis, large in other two)
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
    front_axis_i = 1
    front_sign = -1

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
        print("WARNING: Could not detect faceplate plate. Falling back to front axis=Y, front_sign=-")

    top_lens = [top_bb.xlen, top_bb.ylen, top_bb.zlen]
    front_len = max(top_lens[front_axis_i], 1e-6)

    # define up axis as the largest of remaining; lateral is the leftover
    up_axis_i = max([k for k in range(3) if k != front_axis_i], key=lambda k: top_lens[k])
    lat_axis_i = [k for k in range(3) if k not in (front_axis_i, up_axis_i)][0]

    print(f"Using axes: up={axis_names[up_axis_i]}, front={axis_names[front_axis_i]}, lateral={axis_names[lat_axis_i]}")

    overall_lat_center = [top_bb.center.x, top_bb.center.y, top_bb.center.z][lat_axis_i]
    up_len = max(top_lens[up_axis_i], 1e-6)
    lat_len = max(top_lens[lat_axis_i], 1e-6)

    # 2) Pick a front-protruding lever/handle solid (principal axis aligned to front axis)
    # Tighten criteria toward a "handle" size and position: near mid lateral, mid-to-upper height.
    candidates = []
    for i, s in enumerate(solids):
        if i == plate_idx:
            continue
        bb = s.BoundingBox()
        dims = [bb.xlen, bb.ylen, bb.zlen]
        principal = max(range(3), key=lambda k: dims[k])
        if principal != front_axis_i:
            continue

        length = dims[principal]
        cross_axes = [k for k in range(3) if k != principal]
        cross = [dims[cross_axes[0]], dims[cross_axes[1]]]
        cross_min = min(cross)
        cross_max = max(cross)
        slender = length / max(cross_min, 1e-6)

        # Heuristics for a lever/handle
        if length < 70.0 or length > 260.0:
            continue
        if cross_min < 8.0:
            continue
        if cross_max > 120.0:
            continue
        if slender < 1.8:
            continue

        fc = bb_center(bb, front_axis_i)
        if front_sign > 0:
            front_norm = (fc - bb_min(top_bb, front_axis_i)) / front_len
        else:
            front_norm = (bb_max(top_bb, front_axis_i) - fc) / front_len
        if front_norm < 0.45:
            continue

        uc = bb_center(bb, up_axis_i)
        up_norm = (uc - bb_min(top_bb, up_axis_i)) / up_len

        lc = bb_center(bb, lat_axis_i)
        lat_norm = abs(lc - overall_lat_center) / lat_len

        # Prefer: on front side, somewhat upper, near lateral center
        score = (
            14.0 * front_norm
            + 2.0 * up_norm
            + 0.02 * length
            + 0.35 * slender
            - 2.5 * lat_norm
            - 0.01 * (cross_max - 40.0) ** 2 / 100.0
        )

        candidates.append((score, i, s, bb, dims, length, cross_min, cross_max, slender, front_norm, up_norm, lat_norm))

    if not candidates:
        print("ERROR: Could not find a suitable front-protruding lever/handle candidate. Returning original.")
        return wp_all

    candidates.sort(key=lambda t: t[0], reverse=True)
    score, handle_idx, handle_solid, handle_bb, handle_dims, length, cross_min, cross_max, slender, front_norm, up_norm, lat_norm = candidates[0]
    print(
        f"Selected lever/handle solid idx={handle_idx}, score={score:.3f}, dims={tuple(round(d,2) for d in handle_dims)}, "
        f"length={length:.2f}, slender={slender:.2f}, front_norm={front_norm:.2f}, up_norm={up_norm:.2f}, lat_norm={lat_norm:.2f}"
    )

    # 3) Extend by 50mm in the front direction, using a profile-matched extrusion at the tip.
    ext_len = 50.0  # mm
    dir_vec = [cq.Vector(1, 0, 0), cq.Vector(0, 1, 0), cq.Vector(0, 0, 1)][front_axis_i].multiply(front_sign)

    # Determine a "tip" point at the extreme in the front direction
    sel_v = (">" if front_sign > 0 else "<") + axis_names[front_axis_i]
    hw = cq.Workplane("XY").newObject([handle_solid])
    tip_vertices = hw.vertices(sel_v).vals()
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

    # Small overlap so the boolean union is robust
    overlap = 2.0  # mm

    # Section plane slightly behind the current tip so section yields a closed profile
    sec_origin = tip.add(dir_vec.multiply(-overlap))
    sec_plane = cq.Plane(origin=sec_origin, normal=dir_vec)

    print(f"Tip approx=({tip.x:.3f},{tip.y:.3f},{tip.z:.3f}); extending {ext_len:.2f}mm along {axis_names[front_axis_i]}{'+' if front_sign>0 else '-'}")

    ext_solid = None

    # Try to create a profile-matched extrusion from the section wire
    try:
        sec_wp = cq.Workplane(sec_plane).add(handle_solid).section()
        wires = sec_wp.wires().vals()
        print(f"Section wires found at tip: {len(wires)}")

        faces = []
        for w in wires:
            try:
                if hasattr(w, "isClosed") and not w.isClosed():
                    continue
                f = cq.Face.makeFromWires(w)
                a = f.Area()
                if a > 1e-3:
                    faces.append((a, f))
            except Exception:
                continue

        if faces:
            faces.sort(key=lambda t: t[0], reverse=True)
            a, prof_face = faces[0]
            print(f"Using section profile face area={a:.2f} mm^2")

            vec = dir_vec.multiply(ext_len + overlap)

            # Prefer direct OCC extrusion if available
            made = False
            if hasattr(cq.Solid, "extrudeLinear"):
                try:
                    ext_solid = cq.Solid.extrudeLinear(prof_face, vec)
                    made = True
                except Exception as e:
                    print(f"extrudeLinear failed, will try Workplane extrude. Reason: {e}")

            if not made:
                # Workplane-based extrusion fallback
                try:
                    wp_prof = cq.Workplane(sec_plane).newObject([prof_face])
                    # extrude along workplane normal; ensure correct direction by matching plane normal
                    ext_solid = wp_prof.extrude(ext_len + overlap, combine=False).val()
                    made = True
                except Exception as e:
                    print(f"Workplane extrude failed. Reason: {e}")

        else:
            print("WARNING: Could not form a valid section profile face at tip.")

    except Exception as e:
        print(f"WARNING: Section-based extension failed: {e}")

    # Fallback: simple cylinder based on cross-section bbox estimate (flat end)
    if ext_solid is None:
        cross_axes = [k for k in range(3) if k != front_axis_i]
        r_est = 0.25 * (handle_dims[cross_axes[0]] + handle_dims[cross_axes[1]])
        r_est = max(2.0, min(r_est, 80.0))
        cyl_h = ext_len + overlap
        cyl_start = tip.add(dir_vec.multiply(-overlap))
        print(f"FALLBACK: cylinder extension r_est={r_est:.2f}, h={cyl_h:.2f}")
        ext_solid = cq.Solid.makeCylinder(r_est, cyl_h, cyl_start, dir_vec)

    # Union extension into the full assembly
    result = wp_all.union(ext_solid)

    # Debug: confirm added protrusion in overall bbox along front axis
    bb_before = top_bb
    bb_after = result.val().BoundingBox()
    before_ext = bb_max(bb_before, front_axis_i) if front_sign > 0 else bb_min(bb_before, front_axis_i)
    after_ext = bb_max(bb_after, front_axis_i) if front_sign > 0 else bb_min(bb_after, front_axis_i)
    delta = (after_ext - before_ext) * (1 if front_sign > 0 else -1)
    print(f"Overall front-extreme before={before_ext:.3f}, after={after_ext:.3f}, delta~{delta:.2f}mm (target +50mm, may be lower if other solids define the overall extreme)")

    return result
