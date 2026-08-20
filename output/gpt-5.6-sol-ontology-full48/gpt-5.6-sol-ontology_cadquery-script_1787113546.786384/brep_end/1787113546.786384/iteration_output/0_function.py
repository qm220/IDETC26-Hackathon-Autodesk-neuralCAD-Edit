def my_cad_function(args):
    import os

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    faces = shape.Faces()
    solids = shape.Solids()
    print("Loaded STEP:", input_file)
    print("Valid:", shape.isValid(), "solids:", len(solids), "faces:", len(faces))

    for si, solid in enumerate(solids):
        bb = solid.BoundingBox()
        c = solid.Center()
        print(
            "SOLID", si,
            "valid=", solid.isValid(),
            "volume=", round(solid.Volume(), 6),
            "center=", (round(c.x, 6), round(c.y, 6), round(c.z, 6)),
            "bbox=", (round(bb.xmin, 6), round(bb.ymin, 6), round(bb.zmin, 6),
                       round(bb.xmax, 6), round(bb.ymax, 6), round(bb.zmax, 6)),
            "faces=", len(solid.Faces())
        )

    # Bind the planning-stage FACE 580 identifier to the actual imported topology.
    target_index = 580
    if target_index >= len(faces):
        print("FACE 580 is unavailable in imported topology")
        return model

    target = faces[target_index]
    tc = target.Center()
    tbb = target.BoundingBox()
    print(
        "TARGET FACE", target_index,
        "type=", target.geomType(),
        "area=", round(target.Area(), 6),
        "center=", (round(tc.x, 6), round(tc.y, 6), round(tc.z, 6)),
        "bbox=", (round(tbb.xmin, 6), round(tbb.ymin, 6), round(tbb.zmin, 6),
                   round(tbb.xmax, 6), round(tbb.ymax, 6), round(tbb.zmax, 6)),
        "edges=", len(target.Edges())
    )

    # Establish which disconnected solid owns FACE 580.
    owner_index = None
    for si, solid in enumerate(solids):
        if any(sf.isSame(target) for sf in solid.Faces()):
            owner_index = si
            print("FACE 580 belongs to SOLID", si)
            break

    # Print the target boundary and all faces sharing each boundary edge. This
    # identifies the parent surfaces that must be extended/healed before the
    # replacement chamfer is made.
    for ei, edge in enumerate(target.Edges()):
        ec = edge.Center()
        ebb = edge.BoundingBox()
        adjacent = []
        for fi, face in enumerate(faces):
            if fi == target_index:
                continue
            if any(fe.isSame(edge) for fe in face.Edges()):
                adjacent.append(fi)
        print(
            "FACE580 EDGE", ei,
            "type=", edge.geomType(),
            "length=", round(edge.Length(), 6),
            "center=", (round(ec.x, 6), round(ec.y, 6), round(ec.z, 6)),
            "bbox=", (round(ebb.xmin, 6), round(ebb.ymin, 6), round(ebb.zmin, 6),
                       round(ebb.xmax, 6), round(ebb.ymax, 6), round(ebb.zmax, 6)),
            "adjacent_faces=", adjacent
        )
        for fi in adjacent:
            af = faces[fi]
            ac = af.Center()
            abb = af.BoundingBox()
            print(
                "  ADJ FACE", fi,
                "type=", af.geomType(),
                "area=", round(af.Area(), 6),
                "center=", (round(ac.x, 6), round(ac.y, 6), round(ac.z, 6)),
                "bbox=", (round(abb.xmin, 6), round(abb.ymin, 6), round(abb.zmin, 6),
                           round(abb.xmax, 6), round(abb.ymax, 6), round(abb.zmax, 6))
            )

    # Also report nearby central faces to guard against STEP face-order drift.
    for fi, face in enumerate(faces):
        c = face.Center()
        bb = face.BoundingBox()
        radial = (c.x * c.x + c.z * c.z) ** 0.5
        if radial < 25.0 and bb.xlen < 50.0 and bb.zlen < 50.0:
            if face.geomType() in ("TORUS", "CONE", "CYLINDER"):
                print(
                    "CENTRAL CANDIDATE", fi,
                    "type=", face.geomType(),
                    "area=", round(face.Area(), 6),
                    "center=", (round(c.x, 6), round(c.y, 6), round(c.z, 6)),
                    "bbox=", (round(bb.xmin, 6), round(bb.ymin, 6), round(bb.zmin, 6),
                               round(bb.xmax, 6), round(bb.ymax, 6), round(bb.zmax, 6))
                )

    # Inspection iteration: preserve and return the loaded model unchanged.
    return model