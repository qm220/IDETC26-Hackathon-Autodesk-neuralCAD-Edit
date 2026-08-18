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

    solids = wp_all.solids().vals()
    if not solids:
        print("No solids found; returning original")
        return wp_all

    axis_names = ["X", "Y", "Z"]

    def bb_dim(bb):
        return [bb.xlen, bb.ylen, bb.zlen]

    def bb_center_axis(bb, ai):
        c = bb.center
        return [c.x, c.y, c.z][ai]

    def bb_min(bb, ai):
        return [bb.xmin, bb.ymin, bb.zmin][ai]

    def bb_max(bb, ai):
        return [bb.xmax, bb.ymax, bb.zmax][ai]

    def safe_volume(s):
        try:
            return float(s.Volume())
        except Exception:
            bb = s.BoundingBox()
            return float(bb.xlen * bb.ylen * bb.zlen)

    top_bb = top_shape.BoundingBox()
    print(f"Loaded STEP. Solids found: {len(solids)}")
    print(f"Overall bbox lens (x,y,z): ({top_bb.xlen:.2f}, {top_bb.ylen:.2f}, {top_bb.zlen:.2f})")

    # ---- 1) Identify faceplate-like thin plate to infer FRONT AXIS (normal = thin axis) ----
    plate_candidates = []
    for i, s in enumerate(solids):
        bb = s.BoundingBox()
        dims = bb_dim(bb)
        dims_sorted = sorted(dims)
        min_d, mid_d, max_d = dims_sorted[0], dims_sorted[1], dims_sorted[2]
        if min_d < 10.0 and mid_d > 150.0 and max_d > 150.0:
            score = (mid_d * max_d) / max(min_d, 1e-6)
            plate_candidates.append((score, i, s, bb, dims))

    if not plate_candidates:
        # Fallback: assume front axis is Y
        front_axis_i = 1
        plate_idx = None
        plate_bb = None
        print("WARNING: Could not detect faceplate. Falling back to front axis=Y")
    else:
        plate_candidates.sort(key=lambda t: t[0], reverse=True)
        _, plate_idx, _, plate_bb, plate_dims = plate_candidates[0]
        front_axis_i = min(range(3), key=lambda k: plate_dims[k])
        print(
            f"Faceplate-like solid idx={plate_idx}, dims={tuple(round(d,2) for d in plate_dims)} -> "
            f"front axis={axis_names[front_axis_i]}"
        )

    # ---- 2) Identify main housing as the largest-volume solid (faceplate is thin so will not win) ----
    vol_list = []
    for i, s in enumerate(solids):
        vol_list.append((safe_volume(s), i, s, s.BoundingBox()))
    vol_list.sort(key=lambda t: t[0], reverse=True)
    housing_vol, housing_idx, housing_solid, housing_bb = vol_list[0]
    print(
        f"Housing candidate idx={housing_idx}, approxVol={housing_vol:.1f}, "
        f"dims={tuple(round(d,2) for d in bb_dim(housing_bb))}"
    )

    # ---- 3) Determine FRONT SIGN: use faceplate position relative to housing along the front axis ----
    if plate_bb is not None:
        front_sign = 1 if bb_center_axis(plate_bb, front_axis_i) > bb_center_axis(housing_bb, front_axis_i) else -1
    else:
        # fallback: front side is the nearer extreme to overall min along that axis
        front_sign = -1

    print(f"Front direction: {axis_names[front_axis_i]}{'+' if front_sign>0 else '-'}")

    # Define up axis as the larger of remaining axes (based on overall bbox)
    top_lens = [top_bb.xlen, top_bb.ylen, top_bb.zlen]
    rem = [k for k in range(3) if k != front_axis_i]
    up_axis_i = max(rem, key=lambda k: top_lens[k])
    lat_axis_i = [k for k in range(3) if k not in (front_axis_i, up_axis_i)][0]

    print(f"Using axes: up={axis_names[up_axis_i]}, front={axis_names[front_axis_i]}, lateral={axis_names[lat_axis_i]}")

    dir_vec = [cq.Vector(1, 0, 0), cq.Vector(0, 1, 0), cq.Vector(0, 0, 1)][front_axis_i].multiply(front_sign)

    # Housing front extreme (used for protrusion check)
    housing_front_ext = bb_max(housing_bb, front_axis_i) if front_sign > 0 else bb_min(housing_bb, front_axis_i)

    # ---- 4) Select the protruding lever/handle solid that sticks out of the housing to the front ----
    housing_lat_c = bb_center_axis(housing_bb, lat_axis_i)
    housing_lat_len = max(bb_dim(housing_bb)[lat_axis_i], 1e-6)
    housing_up_min = bb_min(housing_bb, up_axis_i)
    housing_up_len = max(bb_dim(housing_bb)[up_axis_i], 1e-6)

    candidates = []
    for i, s in enumerate(solids):
        if i == plate_idx:
            continue
        # Avoid picking the housing itself
        if i == housing_idx:
            continue

        bb = s.BoundingBox()
        dims = bb_dim(bb)

        # Must be primarily oriented along the front axis (handle sticks out to front)
        principal = max(range(3), key=lambda k: dims[k])
        if principal != front_axis_i:
            continue

        length = dims[front_axis_i]
        cross_axes = [k for k in range(3) if k != front_axis_i]
        cross = [dims[cross_axes[0]], dims[cross_axes[1]]]
        cross_min = min(cross)
        cross_max = max(cross)
        slender = length / max(cross_min, 1e-6)

        # Basic size heuristics for a handle/lever
        if length < 70.0 or length > 260.0:
            continue
        if cross_min < 6.0:
            continue
        if cross_max > 140.0:
            continue
        if slender < 2.0:
            continue

        # Must protrude beyond the housing in the front direction
        solid_front_ext = bb_max(bb, front_axis_i) if front_sign > 0 else bb_min(bb, front_axis_i)
        protrusion = (solid_front_ext - housing_front_ext) * (1 if front_sign > 0 else -1)
        if protrusion < 3.0:
            continue

        # Prefer roughly upper/mid height (where brew/handle typically lives)
        uc = bb_center_axis(bb, up_axis_i)
        up_norm = (uc - housing_up_min) / housing_up_len
        if up_norm < 0.25 or up_norm > 0.90:
            continue

        # Prefer near lateral center
        lc = bb_center_axis(bb, lat_axis_i)
        lat_norm = abs(lc - housing_lat_c) / housing_lat_len

        score = (
            3.0 * protrusion
            + 0.03 * length
            + 0.8 * slender
            + 1.0 * up_norm
            - 2.0 * lat_norm
        )

        candidates.append((score, i, s, bb, protrusion, dims, length, slender, up_norm, lat_norm))

    if not candidates:
        print("ERROR: Could not find a front-protruding handle/lever that protrudes beyond the housing. Returning original.")
        return wp_all

    candidates.sort(key=lambda t: t[0], reverse=True)
    score, handle_idx, handle_solid, handle_bb, protrusion, handle_dims, length, slender, up_norm, lat_norm = candidates[0]
    print(
        f"Selected handle solid idx={handle_idx}, score={score:.3f}, protrusion={protrusion:.2f}mm, "
        f"dims={tuple(round(d,2) for d in handle_dims)}, length={length:.2f}, slender={slender:.2f}, "
        f"up_norm={up_norm:.2f}, lat_norm={lat_norm:.2f}"
    )

    # ---- 5) Extend the handle by 50mm in the front direction ----
    ext_len = 50.0  # mm
    overlap = 2.0   # mm for robust union

    # Tip point: average of vertices at front extreme
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
        # force tip to front extreme
        if front_axis_i == 0:
            tip.x = handle_bb.xmax if front_sign > 0 else handle_bb.xmin
        elif front_axis_i == 1:
            tip.y = handle_bb.ymax if front_sign > 0 else handle_bb.ymin
        else:
            tip.z = handle_bb.zmax if front_sign > 0 else handle_bb.zmin

    print(
        f"Tip approx=({tip.x:.3f},{tip.y:.3f},{tip.z:.3f}); "
        f"extending +{ext_len:.2f}mm along {axis_names[front_axis_i]}{'+' if front_sign>0 else '-'}"
    )

    # Section plane slightly behind the tip so we capture a closed profile
    sec_origin = tip.add(dir_vec.multiply(-overlap))
    sec_plane = cq.Plane(origin=sec_origin, normal=dir_vec)

    ext_solid = None
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

        if not faces:
            raise ValueError("No valid closed section face from tip section")

        faces.sort(key=lambda t: t[0], reverse=True)
        a, prof_face = faces[0]
        print(f"Using section profile face area={a:.2f} mm^2")

        vec = dir_vec.multiply(ext_len + overlap)

        # Prefer OCC linear extrusion if available
        if hasattr(cq.Solid, "extrudeLinear"):
            try:
                ext_solid = cq.Solid.extrudeLinear(prof_face, vec)
            except Exception as e:
                print(f"extrudeLinear failed; falling back to Workplane extrude. Reason: {e}")

        if ext_solid is None:
            wp_prof = cq.Workplane(sec_plane).newObject([prof_face])
            ext_solid = wp_prof.extrude(ext_len + overlap, combine=False).val()

    except Exception as e:
        print(f"WARNING: Section-based extension failed: {e}")

    # Fallback: cylinder based on cross-section bbox estimate
    if ext_solid is None:
        cross_axes = [k for k in range(3) if k != front_axis_i]
        r_est = 0.25 * (handle_dims[cross_axes[0]] + handle_dims[cross_axes[1]])
        r_est = max(2.0, min(r_est, 120.0))
        cyl_h = ext_len + overlap
        cyl_start = tip.add(dir_vec.multiply(-overlap))
        print(f"FALLBACK: cylinder extension r_est={r_est:.2f}, h={cyl_h:.2f}")
        ext_solid = cq.Solid.makeCylinder(r_est, cyl_h, cyl_start, dir_vec)

    # Debug: check extension reach vs handle tip
    ext_bb = ext_solid.BoundingBox()
    handle_front_ext = bb_max(handle_bb, front_axis_i) if front_sign > 0 else bb_min(handle_bb, front_axis_i)
    ext_front_ext = bb_max(ext_bb, front_axis_i) if front_sign > 0 else bb_min(ext_bb, front_axis_i)
    delta_tip = (ext_front_ext - handle_front_ext) * (1 if front_sign > 0 else -1)
    print(
        f"Handle front extreme={handle_front_ext:.3f}; extension front extreme={ext_front_ext:.3f}; "
        f"added beyond tip ~{delta_tip:.2f}mm (target ~{ext_len:.2f}mm)"
    )

    # Union extension into the full assembly
    result = wp_all.union(ext_solid)

    return result
