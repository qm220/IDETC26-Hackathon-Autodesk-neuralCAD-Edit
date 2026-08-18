def my_cad_function(args):
    import cadquery as cq
    import os

    input_file = os.path.expanduser(args.get("input_file", ""))
    if not input_file or not os.path.exists(input_file):
        raise ValueError(f"Missing/invalid args['input_file']: {input_file}")

    model = cq.importers.importStep(input_file)

    shp = model.val() if hasattr(model, "val") else model
    bb = shp.BoundingBox()
    print(f"Loaded STEP: {input_file}")
    print(f"Model valid: {shp.isValid()}")
    print(f"Bbox min=({bb.xmin:.3f},{bb.ymin:.3f},{bb.zmin:.3f}) max=({bb.xmax:.3f},{bb.ymax:.3f},{bb.zmax:.3f})")

    # --- Locate the front side face at z≈0 (normal +Z) ---
    plus_z_faces = list(model.faces(">Z").vals())
    if not plus_z_faces:
        raise RuntimeError("No faces with normal >Z found; cannot locate front face at z=0")

    # Prefer the +Z face with the greatest zmax (closest to z=0), and large area
    def face_score(f):
        fbb = f.BoundingBox()
        return (round(fbb.zmax, 6), f.Area())

    plus_z_faces.sort(key=face_score, reverse=True)
    front_face = plus_z_faces[0]
    fbb = front_face.BoundingBox()
    print(f"Front(+Z) face chosen: zmax={fbb.zmax:.4f}, zmin={fbb.zmin:.4f}, area={front_face.Area():.2f}")

    # --- Find the obround slot opening wire on that face by wire bounding-box heuristics ---
    wires = list(front_face.Wires())
    print(f"Front face wire count (outer+inner): {len(wires)}")

    candidates = []
    for i, w in enumerate(wires):
        wbb = w.BoundingBox()
        xlen = wbb.xmax - wbb.xmin
        ylen = wbb.ymax - wbb.ymin
        xc, yc, zc = wbb.center.x, wbb.center.y, wbb.center.z

        print(f"  wire[{i}]: ctr=({xc:.3f},{yc:.3f},{zc:.3f}) xlen={xlen:.3f} ylen={ylen:.3f}")

        # Expect obround width ~18 (R=9 ends), vertical orientation => ylen > xlen
        # Also expect it to be in the web region (above base), so yc should be well above y=15.
        if 14.0 <= xlen <= 22.5 and ylen >= xlen * 1.2 and 60.0 <= xc <= 150.0 and yc >= 25.0:
            # Score closer to expected width 18 and expected x center ~113
            score = abs(xlen - 18.0) * 2.0 + abs(xc - 113.0) * 0.5
            candidates.append((score, i, w, wbb, xlen, ylen))

    if not candidates:
        raise RuntimeError(
            "Could not identify the vertical obround slot opening wire on the front face. "
            "Use the printed wire bounding boxes to adjust heuristics."
        )

    candidates.sort(key=lambda t: t[0])
    score, wi, slot_wire, slot_bb, slot_w, slot_L = candidates[0]
    slot_cx, slot_cy = slot_bb.center.x, slot_bb.center.y
    print(
        f"Selected slot wire index={wi} score={score:.3f} center=({slot_cx:.3f},{slot_cy:.3f}) "
        f"width(x)~{slot_w:.3f} length(y)~{slot_L:.3f}"
    )

    # --- Cut it through the complete main-body thickness (z=0 -> z=-42) ---
    # Use generous depth; since the profile is located in the web region, it shouldn't affect the flange.
    cut_depth = 80.0

    # slot2D(length, diameter). Default is along X; rotate 90° so the long axis is along Y.
    cutter = (
        cq.Workplane("XY")
        .center(slot_cx, slot_cy)
        .slot2D(slot_L, slot_w, angle=90)
        .extrude(-cut_depth)
    )

    result = model.cut(cutter)

    res_shp = result.val() if hasattr(result, "val") else result
    print(f"Result valid: {res_shp.isValid()}")
    print(f"Result faces: {len(res_shp.Faces())}")

    # --- Optional check: look for a -Z face near z≈-42 that now contains a similar inner wire ---
    minus_z_faces = list(result.faces("<Z").vals())
    print(f"Candidate <Z faces: {len(minus_z_faces)}")

    # Find a likely back main-body face around z=-42 (not the flange back face at z=-60)
    back_like = []
    for f in minus_z_faces:
        fbb2 = f.BoundingBox()
        zc2 = fbb2.center.z
        if -50.0 < zc2 < -30.0:  # around -42
            back_like.append((abs(zc2 + 42.0), f.Area(), f, fbb2))

    if back_like:
        back_like.sort(key=lambda t: (t[0], -t[1]))
        _, _, back_face, back_bb = back_like[0]
        print(f"Back-like face chosen: center.z={back_bb.center.z:.3f}, area={back_face.Area():.2f}")
        bwires = list(back_face.Wires())
        print(f"Back-like face wire count: {len(bwires)}")
        for i, w in enumerate(bwires[:20]):
            wbb = w.BoundingBox()
            xlen = wbb.xmax - wbb.xmin
            ylen = wbb.ymax - wbb.ymin
            print(f"  back wire[{i}]: ctr=({wbb.center.x:.3f},{wbb.center.y:.3f},{wbb.center.z:.3f}) xlen={xlen:.3f} ylen={ylen:.3f}")

    return result
