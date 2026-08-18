def my_cad_function(args):
    import cadquery as cq
    import os
    
    input_file = os.path.expanduser(args.get("input_file", ""))
    if not input_file or not os.path.exists(input_file):
        raise ValueError(f"Missing/invalid args['input_file']: {input_file}")

    model = cq.importers.importStep(input_file)

    # Basic model info
    shp = model.val() if hasattr(model, "val") else model
    bb = shp.BoundingBox()
    print(f"Loaded STEP: {input_file}")
    print(f"Model valid: {shp.isValid()}")
    print(f"Bbox min=({bb.xmin:.3f},{bb.ymin:.3f},{bb.zmin:.3f}) max=({bb.xmax:.3f},{bb.ymax:.3f},{bb.zmax:.3f})")

    # 1) Find the front side planar face at z≈0 (normal +Z), assumed to be the largest +Z face.
    front_wp = model.faces(">Z").sortBy(lambda f: f.Area(), reverse=True)
    if front_wp.size() == 0:
        raise RuntimeError("No faces with normal >Z found; cannot locate front face at z=0")

    front_face = front_wp.first().val()
    fbb = front_face.BoundingBox()
    print(f"Front (+Z) face bbox z-range: {fbb.zmin:.4f}..{fbb.zmax:.4f}")

    # 2) On this face, identify the obround slot opening by scanning inner wires.
    wires = list(front_face.Wires())
    print(f"Front face wire count (outer+inner): {len(wires)}")

    # Compute bounding boxes for each wire and choose the one that matches the known obround slot size:
    # expected approx: width ~18 (R=9), x in ~104..122 region => center x ~113, and length > width.
    candidates = []
    for i, w in enumerate(wires):
        wbb = w.BoundingBox()
        xlen = wbb.xmax - wbb.xmin
        ylen = wbb.ymax - wbb.ymin
        zc = wbb.center.z
        xc = wbb.center.x
        yc = wbb.center.y
        print(
            f"  wire[{i}]: ctr=({xc:.3f},{yc:.3f},{zc:.3f}) xlen={xlen:.3f} ylen={ylen:.3f}"
        )

        # Heuristic filter
        if 14.0 <= xlen <= 22.0 and ylen > xlen * 1.2 and 80.0 <= xc <= 140.0:
            # Score closer to expected x center ~113 and width ~18
            score = abs(xc - 113.0) + 2.0 * abs(xlen - 18.0)
            candidates.append((score, i, w, wbb, xlen, ylen))

    if not candidates:
        raise RuntimeError(
            "Could not identify the vertical obround slot opening wire on the front face. "
            "See printed wire bounding boxes to adjust heuristics."
        )

    candidates.sort(key=lambda t: t[0])
    score, wi, slot_wire, slot_bb, slot_w, slot_L = candidates[0]
    slot_cx, slot_cy = slot_bb.center.x, slot_bb.center.y
    print(
        f"Selected slot wire index={wi} score={score:.3f} center=({slot_cx:.3f},{slot_cy:.3f}) width~{slot_w:.3f} length~{slot_L:.3f}"
    )

    # 3) Perform a new through cut by recreating the same obround slot profile and extruding in -Z.
    # Use a conservative depth to guarantee going past the back face (z≈-42) but avoid relying on exact thickness.
    # (The slot is in the web region, above the base flange, so extra depth should not affect the flange.)
    cut_depth = max(80.0, abs(bb.zmin) + 10.0)  # mm

    # CadQuery slot2D: angle rotates the slot; 90 deg makes the long axis along +Y.
    slot_profile = (
        cq.Workplane("XY")
        .center(slot_cx, slot_cy)
        .slot2D(slot_L, slot_w, angle=90)
        .extrude(-cut_depth)
    )

    result = model.cut(slot_profile)

    # Optional sanity print
    res_shp = result.val() if hasattr(result, "val") else result
    print(f"Result valid: {res_shp.isValid()}")
    print(f"Result faces: {len(res_shp.Faces())}")

    return result
