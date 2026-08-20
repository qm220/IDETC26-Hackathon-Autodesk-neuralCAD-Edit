def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    print(f"Model valid: {shape.isValid()}")
    print(f"Solids: {len(shape.Solids())}, faces: {len(shape.Faces())}, edges: {len(shape.Edges())}")
    bb = shape.BoundingBox()
    print(f"BBox: x=({bb.xmin:.6f}, {bb.xmax:.6f}), y=({bb.ymin:.6f}, {bb.ymax:.6f}), z=({bb.zmin:.6f}, {bb.zmax:.6f})")

    # Grounded bore-wall faces from F002 and F004 in model.json.
    target_face_ids = [44, 46, 49, 50, 51, 52]
    faces = shape.Faces()

    for face_id in target_face_ids:
        face = faces[face_id]
        c = face.Center()
        fbb = face.BoundingBox()
        try:
            geom_type = face.geomType()
        except Exception:
            geom_type = "unknown"
        print(
            f"FACE {face_id}: type={geom_type}, area={face.Area():.9f}, "
            f"center=({c.x:.6f},{c.y:.6f},{c.z:.6f}), "
            f"bbox=x({fbb.xmin:.6f},{fbb.xmax:.6f}) "
            f"y({fbb.ymin:.6f},{fbb.ymax:.6f}) "
            f"z({fbb.zmin:.6f},{fbb.zmax:.6f}), edges={len(face.Edges())}"
        )
        for local_i, edge in enumerate(face.Edges()):
            ec = edge.Center()
            ebb = edge.BoundingBox()
            try:
                edge_type = edge.geomType()
            except Exception:
                edge_type = "unknown"
            try:
                length = edge.Length()
            except Exception:
                length = -1.0
            print(
                f"  edge {local_i}: type={edge_type}, length={length:.9f}, "
                f"center=({ec.x:.6f},{ec.y:.6f},{ec.z:.6f}), "
                f"bbox=x({ebb.xmin:.6f},{ebb.xmax:.6f}) "
                f"y({ebb.ymin:.6f},{ebb.ymax:.6f}) "
                f"z({ebb.zmin:.6f},{ebb.zmax:.6f})"
            )

    return model