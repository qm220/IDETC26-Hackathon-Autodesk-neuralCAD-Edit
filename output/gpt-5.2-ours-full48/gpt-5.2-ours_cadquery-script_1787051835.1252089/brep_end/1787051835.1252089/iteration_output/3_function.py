def my_cad_function(args):
    import cadquery as cq
    import os

    input_file = os.path.expanduser(args.get("input_file", ""))
    if not input_file or not os.path.exists(input_file):
        raise ValueError(f"Missing or invalid args['input_file']: {input_file}")

    wp_in = cq.importers.importStep(input_file)
    root = wp_in.val() if hasattr(wp_in, "val") else wp_in

    def solids_from(shape):
        try:
            return list(shape.Solids())
        except Exception:
            try:
                return list(cq.Workplane(obj=shape).solids().vals())
            except Exception:
                return []

    def biggest_solid(shape):
        sols = solids_from(shape)
        if not sols:
            return None
        return max(sols, key=lambda s: float(s.Volume()))

    main = biggest_solid(root)
    if main is None:
        raise ValueError("No solids found in imported STEP")

    bb = main.BoundingBox()
    xmin, xmax = bb.xmin, bb.xmax
    ymin, ymax = bb.ymin, bb.ymax
    zmin, zmax = bb.zmin, bb.zmax
    xlen, ylen, zlen = bb.xlen, bb.ylen, bb.zlen
    ymid = 0.5 * (ymin + ymax)

    print(f"MAIN BBOX: x[{xmin:.3f},{xmax:.3f}] y[{ymin:.3f},{ymax:.3f}] z[{zmin:.3f},{zmax:.3f}]  ymid={ymid:.3f}")

    # --- Region of interest: the larger 'head' mass on x-min side ---
    # Keep away from pocket (starts ~x=125 per planning); include a little into arm but not to pocket.
    head_xmax = xmin + min(110.0, 0.40 * xlen)
    margin = max(1.0, 0.01 * max(xlen, ylen, zlen))

    # Build an oversized box to slice out the head region
    head_box = cq.Solid.makeBox(
        (head_xmax - xmin) + 2 * margin,
        ylen + 2 * margin,
        zlen + 2 * margin,
        cq.Vector(xmin - margin, ymin - margin, zmin - margin),
    )

    head_chunk_raw = main.intersect(head_box)
    rest_chunk_raw = main.cut(head_box)

    head_chunk = biggest_solid(head_chunk_raw) if head_chunk_raw is not None else None
    rest_chunk = biggest_solid(rest_chunk_raw) if rest_chunk_raw is not None else None

    if head_chunk is None or rest_chunk is None:
        print("Head/rest split failed; returning original")
        return cq.Workplane(obj=main)

    bb_h = head_chunk.BoundingBox()
    print(
        f"HEAD CHUNK BBOX: x[{bb_h.xmin:.3f},{bb_h.xmax:.3f}] y[{bb_h.ymin:.3f},{bb_h.ymax:.3f}] z[{bb_h.zmin:.3f},{bb_h.zmax:.3f}]"
    )

    tolY = max(0.5, 0.015 * ylen)

    def fcenter(f):
        try:
            return f.Center()
        except Exception:
            return f.centerOfMass()

    def touches_y_plane(f, y_target):
        fb = f.BoundingBox()
        return abs(fb.ymin - y_target) <= tolY or abs(fb.ymax - y_target) <= tolY

    def curved_face_score_near_y(shape, y_target):
        # Score based on curved face area near that side (more curved area implies existing radii/blends)
        score = 0.0
        nfaces = 0
        for f in shape.Faces():
            try:
                gt = f.geomType()
            except Exception:
                continue
            if gt not in ("CYLINDER", "SPHERE", "TORUS", "BSPLINE", "BEZIER"):
                continue
            if not touches_y_plane(f, y_target):
                continue
            try:
                a = float(f.Area())
            except Exception:
                a = 0.0
            # prefer faces that are really on the head (avoid midplane artifacts)
            c = fcenter(f)
            if c.x > head_xmax + 1e-6:
                continue
            score += a
            nfaces += 1
        return score, nfaces

    score_ymin, ncurv_ymin = curved_face_score_near_y(head_chunk, ymin)
    score_ymax, ncurv_ymax = curved_face_score_near_y(head_chunk, ymax)

    print(f"Curved-face score near y-min({ymin:.3f}): area={score_ymin:.3f}, n={ncurv_ymin}")
    print(f"Curved-face score near y-max({ymax:.3f}): area={score_ymax:.3f}, n={ncurv_ymax}")

    # Choose the side with MORE curved area as the 'good' side; mirror it to rebuild the other side.
    good_is_ymin = (score_ymin > score_ymax) or (score_ymin == score_ymax)
    good_side = ymin if good_is_ymin else ymax
    bad_side = ymax if good_is_ymin else ymin
    print(f"Symmetry repair: good_side_y={good_side:.3f} -> mirror across y={ymid:.3f} to fix bad_side_y={bad_side:.3f}")

    # Intersect head_chunk with a half-space box on the good side, including a small overlap past midplane.
    if good_is_ymin:
        y0 = ymin - margin
        dy = (ymid - y0) + 2 * margin  # extend past mid a bit for robust union
    else:
        y0 = ymid - margin
        dy = (ymax + margin) - y0

    good_half_box = cq.Solid.makeBox(
        (head_xmax - xmin) + 2 * margin,
        dy,
        zlen + 2 * margin,
        cq.Vector(xmin - margin, y0, zmin - margin),
    )

    good_half_raw = head_chunk.intersect(good_half_box)
    good_half = biggest_solid(good_half_raw) if good_half_raw is not None else None
    if good_half is None:
        print("Good-half extraction failed; returning original")
        return cq.Workplane(obj=main)

    # Mirror the good half across the mid-plane y=ymid (plane normal is +Y)
    mirror_plane = cq.Plane(origin=(0, ymid, 0), normal=(0, 1, 0))
    mirrored_half = good_half.mirror(mirror_plane)

    # Rebuild symmetric head
    try:
        sym_head_raw = good_half.union(mirrored_half)
    except Exception as ex:
        print(f"Union of mirrored head halves failed: {ex}; returning original")
        return cq.Workplane(obj=main)

    sym_head = biggest_solid(sym_head_raw) if sym_head_raw is not None else None
    if sym_head is None:
        print("Symmetric head creation produced no solid; returning original")
        return cq.Workplane(obj=main)

    # Fuse back with the untouched rest of the part
    try:
        final_raw = rest_chunk.union(sym_head)
    except Exception as ex:
        print(f"Final union failed: {ex}; returning original")
        return cq.Workplane(obj=main)

    final = biggest_solid(final_raw)
    if final is None:
        print("Final result produced no solid; returning original")
        return cq.Workplane(obj=main)

    bb_f = final.BoundingBox()
    print(f"FINAL BBOX: x[{bb_f.xmin:.3f},{bb_f.xmax:.3f}] y[{bb_f.ymin:.3f},{bb_f.ymax:.3f}] z[{bb_f.zmin:.3f},{bb_f.zmax:.3f}]")

    return cq.Workplane(obj=final)
