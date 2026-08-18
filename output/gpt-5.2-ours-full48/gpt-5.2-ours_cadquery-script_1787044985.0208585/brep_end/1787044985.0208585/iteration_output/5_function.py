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
    print(f"Loaded STEP. Solids found: {len(solids)}")
    if not solids:
        print("No solids found; returning original")
        return wp_all

    axis_names = ["X", "Y", "Z"]
    axis_vecs = [cq.Vector(1, 0, 0), cq.Vector(0, 1, 0), cq.Vector(0, 0, 1)]

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

    # --- Identify housing as largest-volume solid ---
    vol_list = []
    for i, s in enumerate(solids):
        vol_list.append((safe_volume(s), i, s, s.BoundingBox()))
    vol_list.sort(key=lambda t: t[0], reverse=True)
    housing_vol, housing_idx, housing_solid, housing_bb = vol_list[0]
    h_dims = bb_dim(housing_bb)
    h_ctr = housing_bb.center
    print(
        f"Housing candidate idx={housing_idx}, vol={housing_vol:.1f}, dims={tuple(round(d,2) for d in h_dims)}, "
        f"center=({h_ctr.x:.2f},{h_ctr.y:.2f},{h_ctr.z:.2f})"
    )

    # --- Heuristic to find the actuation lever/rod solid (slender, near center, protrudes from housing) ---
    candidates = []
    for i, s in enumerate(solids):
        if i == housing_idx:
            continue
        bb = s.BoundingBox()
        dims = bb_dim(bb)
        vol = safe_volume(s)

        p = max(range(3), key=lambda k: dims[k])
        L = dims[p]
        cross_axes = [k for k in range(3) if k != p]
        c1, c2 = dims[cross_axes[0]], dims[cross_axes[1]]
        cmax = max(c1, c2)
        cmin = min(c1, c2)
        slender = L / max(cmax, 1e-6)

        # Basic rod/lever size gates
        if L < 80.0 or L > 380.0:
            continue
        if cmin < 4.0:
            continue
        if cmax > 90.0:  # exclude big handles/blocks
            continue
        if slender < 2.6:
            continue

        # Protrusion beyond housing along the principal axis
        pos = bb_max(bb, p) - bb_max(housing_bb, p)
        neg = bb_min(housing_bb, p) - bb_min(bb, p)
        protr = max(pos, neg)
        if protr < 6.0:
            continue

        # Prefer near housing center in the two cross axes
        lat_pen = 0.0
        for ax in cross_axes:
            lat_pen += abs(bb_center_axis(bb, ax) - bb_center_axis(housing_bb, ax)) / max(h_dims[ax], 1e-6)

        # Prefer smaller volume (rod is small)
        vol_pen = vol / max(housing_vol, 1e-6)

        score = 6.0 * protr + 8.0 * slender - 10.0 * lat_pen - 40.0 * vol_pen
        candidates.append((score, i, s, bb, p, pos, neg, protr, dims, slender, lat_pen, vol))

    # Fallback: if none found with protrusion criterion, just pick most slender small solid
    if not candidates:
        print("WARNING: No protruding rod/lever candidate found with protrusion test; using fallback slender-solid search.")
        for i, s in enumerate(solids):
            if i == housing_idx:
                continue
            bb = s.BoundingBox()
            dims = bb_dim(bb)
            vol = safe_volume(s)
            p = max(range(3), key=lambda k: dims[k])
            L = dims[p]
            cross_axes = [k for k in range(3) if k != p]
            cmax = max(dims[cross_axes[0]], dims[cross_axes[1]])
            cmin = min(dims[cross_axes[0]], dims[cross_axes[1]])
            slender = L / max(cmax, 1e-6)
            if L < 80.0 or cmax > 90.0 or cmin < 4.0 or slender < 3.0:
                continue
            lat_pen = 0.0
            for ax in cross_axes:
                lat_pen += abs(bb_center_axis(bb, ax) - bb_center_axis(housing_bb, ax)) / max(h_dims[ax], 1e-6)
            vol_pen = vol / max(housing_vol, 1e-6)
            score = 8.0 * slender - 8.0 * lat_pen - 40.0 * vol_pen
            # set pos/neg/protr placeholders
            candidates.append((score, i, s, bb, p, 0.0, 0.0, 0.0, dims, slender, lat_pen, vol))

    if not candidates:
        print("ERROR: Could not identify lever/rod solid. Returning original.")
        return wp_all

    candidates.sort(key=lambda t: t[0], reverse=True)
    score, lever_idx, lever_solid, lever_bb, p, pos, neg, protr, dims, slender, lat_pen, vol = candidates[0]

    # Decide extension direction: the side that is farther outside housing along principal axis
    if pos >= neg:
        sign = 1
        protr_used = pos
    else:
        sign = -1
        protr_used = neg

    axis = axis_names[p]
    dir_vec = axis_vecs[p].multiply(sign)

    print(
        f"Selected lever candidate idx={lever_idx}, score={score:.3f}, axis={axis}{'+' if sign>0 else '-'}, "
        f"dims={tuple(round(d,2) for d in dims)}, slender={slender:.2f}, protrusion_used={protr_used:.2f}mm"
    )

    # --- Extend by 50mm along its axis at the free end ---
    ext_len = 50.0  # mm
    overlap = 2.0   # mm

    # Find tip point at extreme end of lever along chosen axis/sign
    sel_v = (">" if sign > 0 else "<") + axis
    lw = cq.Workplane("XY").newObject([lever_solid])
    tip_vertices = lw.vertices(sel_v).vals()

    if tip_vertices:
        pts = [v.Center() for v in tip_vertices]
        tip = cq.Vector(
            sum(p_.x for p_ in pts) / len(pts),
            sum(p_.y for p_ in pts) / len(pts),
            sum(p_.z for p_ in pts) / len(pts),
        )
    else:
        c = lever_bb.center
        tip = cq.Vector(c.x, c.y, c.z)
        # force to extreme
        if p == 0:
            tip.x = lever_bb.xmax if sign > 0 else lever_bb.xmin
        elif p == 1:
            tip.y = lever_bb.ymax if sign > 0 else lever_bb.ymin
        else:
            tip.z = lever_bb.zmax if sign > 0 else lever_bb.zmin

    print(f"Lever tip approx at ({tip.x:.3f},{tip.y:.3f},{tip.z:.3f}); extending {ext_len:.2f}mm along {axis}{'+' if sign>0 else '-'}")

    # Section plane slightly inside the tip to capture a closed profile
    sec_origin = tip.add(dir_vec.multiply(-overlap))
    sec_plane = cq.Plane(origin=sec_origin, normal=dir_vec)

    ext_solid = None
    try:
        sec_wp = cq.Workplane(sec_plane).add(lever_solid).section()
        wires = sec_wp.wires().vals()
        print(f"Section wires at lever tip: {len(wires)}")

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
            raise ValueError("No closed section face could be created")

        faces.sort(key=lambda t: t[0], reverse=True)
        a, prof_face = faces[0]
        print(f"Using section profile area={a:.2f} mm^2")

        # Extrude outward by ext_len + overlap
        vec = dir_vec.multiply(ext_len + overlap)
        if hasattr(cq.Solid, "extrudeLinear"):
            try:
                ext_solid = cq.Solid.extrudeLinear(prof_face, vec)
            except Exception as e:
                print(f"extrudeLinear failed: {e}; falling back to Workplane extrude")

        if ext_solid is None:
            wp_prof = cq.Workplane(sec_plane).newObject([prof_face])
            ext_solid = wp_prof.extrude(ext_len + overlap, combine=False).val()

    except Exception as e:
        print(f"WARNING: Section-based extension failed: {e}")

    if ext_solid is None:
        # Fallback cylinder extension based on cross dims
        cross_axes = [k for k in range(3) if k != p]
        r_est = 0.25 * (dims[cross_axes[0]] + dims[cross_axes[1]])
        r_est = max(2.0, min(r_est, 60.0))
        print(f"FALLBACK: cylinder extension with r_est={r_est:.2f}mm")
        cyl_h = ext_len + overlap
        cyl_start = tip.add(dir_vec.multiply(-overlap))
        ext_solid = cq.Solid.makeCylinder(r_est, cyl_h, cyl_start, dir_vec)

    # Debug reach
    lever_front_ext = bb_max(lever_bb, p) if sign > 0 else bb_min(lever_bb, p)
    ext_bb = ext_solid.BoundingBox()
    ext_front_ext = bb_max(ext_bb, p) if sign > 0 else bb_min(ext_bb, p)
    added = (ext_front_ext - lever_front_ext) * (1 if sign > 0 else -1)
    print(
        f"Lever extreme={lever_front_ext:.3f}; extension extreme={ext_front_ext:.3f}; "
        f"added ~{added:.2f}mm (target {ext_len:.2f}mm)"
    )

    result = wp_all.union(ext_solid)
    return result
