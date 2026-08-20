def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    print("=== START MODEL INSPECTION ===")
    print(f"Valid: {shape.isValid()}")
    print(f"Total solids: {len(shape.Solids())}")
    print(f"Total faces: {len(shape.Faces())}")
    print(f"Total edges: {len(shape.Edges())}")

    for si, solid in enumerate(shape.Solids()):
        bb = solid.BoundingBox()
        c = solid.Center()
        print(
            f"SOLID {si}: volume={solid.Volume():.6f}, "
            f"center=({c.x:.6f},{c.y:.6f},{c.z:.6f}), "
            f"bbox=({bb.xmin:.6f},{bb.ymin:.6f},{bb.zmin:.6f}) to "
            f"({bb.xmax:.6f},{bb.ymax:.6f},{bb.zmax:.6f}), "
            f"faces={len(solid.Faces())}"
        )

    important_faces = {
        0, 1, 3, 5, 6, 7, 9, 10, 11, 14, 15, 20,
        23, 24, 27, 31, 33, 36, 37, 41, 42, 43, 45,
        53, 58, 72, 77, 85, 86, 87, 88, 89
    }

    faces = shape.Faces()
    for i, face in enumerate(faces):
        if i not in important_faces:
            continue
        bb = face.BoundingBox()
        c = face.Center()
        try:
            geom = face.geomType()
        except Exception:
            geom = "UNKNOWN"
        try:
            n = face.normalAt()
            normal_text = f"({n.x:.6f},{n.y:.6f},{n.z:.6f})"
        except Exception:
            normal_text = "n/a"
        print(
            f"FACE {i}: type={geom}, area={face.Area():.6f}, "
            f"center=({c.x:.6f},{c.y:.6f},{c.z:.6f}), normal={normal_text}, "
            f"bbox=({bb.xmin:.6f},{bb.ymin:.6f},{bb.zmin:.6f}) to "
            f"({bb.xmax:.6f},{bb.ymax:.6f},{bb.zmax:.6f}), "
            f"edges={len(face.Edges())}"
        )

    # Print the longest edges to identify the longitudinal blade boundaries and
    # verify which existing surfaces provide the intended edge-radius reference.
    edge_data = []
    for i, edge in enumerate(shape.Edges()):
        try:
            length = edge.Length()
            c = edge.Center()
            bb = edge.BoundingBox()
            edge_data.append((length, i, c, bb, edge.geomType()))
        except Exception:
            pass
    edge_data.sort(key=lambda item: item[0], reverse=True)
    print("=== LONGEST EDGES ===")
    for length, i, c, bb, geom in edge_data[:30]:
        print(
            f"EDGE {i}: type={geom}, length={length:.6f}, "
            f"center=({c.x:.6f},{c.y:.6f},{c.z:.6f}), "
            f"bbox=({bb.xmin:.6f},{bb.ymin:.6f},{bb.zmin:.6f}) to "
            f"({bb.xmax:.6f},{bb.ymax:.6f},{bb.zmax:.6f})"
        )

    print("=== END MODEL INSPECTION ===")
    return model