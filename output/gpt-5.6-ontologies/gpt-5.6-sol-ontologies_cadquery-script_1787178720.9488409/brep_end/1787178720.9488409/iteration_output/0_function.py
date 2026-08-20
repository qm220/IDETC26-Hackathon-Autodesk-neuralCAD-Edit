def my_cad_function(args):
    import os
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    solids = shape.Solids()
    faces = shape.Faces()
    bb = shape.BoundingBox()
    print("MODEL valid=", shape.isValid(), "solids=", len(solids), "faces=", len(faces))
    print("MODEL bbox:", (bb.xmin, bb.ymin, bb.zmin), "to", (bb.xmax, bb.ymax, bb.zmax), "center=", (bb.center.x, bb.center.y, bb.center.z))

    for i, solid in enumerate(solids):
        sb = solid.BoundingBox()
        print("SOLID", i,
              "faces=", len(solid.Faces()),
              "volume=", round(solid.Volume(), 3),
              "bbox=", tuple(round(v, 3) for v in (sb.xmin, sb.ymin, sb.zmin, sb.xmax, sb.ymax, sb.zmax)),
              "center=", tuple(round(v, 3) for v in (sb.center.x, sb.center.y, sb.center.z)))

    target_indices = list(range(296, 308)) + list(range(361, 373))
    for idx in target_indices:
        if idx >= len(faces):
            print("FACE", idx, "OUT OF RANGE")
            continue
        face = faces[idx]
        fb = face.BoundingBox()
        c = face.Center()
        owners = []
        for si, solid in enumerate(solids):
            if any(face.isSame(sf) for sf in solid.Faces()):
                owners.append(si)
        try:
            gt = face.geomType()
        except Exception:
            gt = "unknown"
        print("FACE", idx,
              "type=", gt,
              "owner_solids=", owners,
              "area=", round(face.Area(), 3),
              "center=", tuple(round(v, 3) for v in (c.x, c.y, c.z)),
              "bbox=", tuple(round(v, 3) for v in (fb.xmin, fb.ymin, fb.zmin, fb.xmax, fb.ymax, fb.zmax)))

    # Print detailed edge/vertex information for the grounded Cordholder and handle solids.
    grounded_faces = [296, 361]
    grounded_solids = set()
    for idx in grounded_faces:
        if idx < len(faces):
            for si, solid in enumerate(solids):
                if any(faces[idx].isSame(sf) for sf in solid.Faces()):
                    grounded_solids.add(si)
    for si in sorted(grounded_solids):
        solid = solids[si]
        print("DETAIL SOLID", si)
        for vi, vertex in enumerate(solid.Vertices()):
            p = vertex.Center()
            print("  V", vi, tuple(round(v, 3) for v in (p.x, p.y, p.z)))

    return model