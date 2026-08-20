def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    print(f"Model valid: {shape.isValid()}")
    print(f"Solids: {len(shape.Solids())}, Faces: {len(shape.Faces())}, Edges: {len(shape.Edges())}")
    bb = shape.BoundingBox()
    print(
        f"Model bbox: xmin={bb.xmin:.6f}, xmax={bb.xmax:.6f}, "
        f"ymin={bb.ymin:.6f}, ymax={bb.ymax:.6f}, "
        f"zmin={bb.zmin:.6f}, zmax={bb.zmax:.6f}"
    )

    faces_by_id = {}
    for index, face in enumerate(shape.Faces()):
        face_id = f"FACE {index}"
        faces_by_id[face_id] = face
        center = face.Center()
        fbb = face.BoundingBox()
        geom_type = face.geomType()
        try:
            normal = face.normalAt(center)
            normal_text = f"({normal.x:.6f}, {normal.y:.6f}, {normal.z:.6f})"
        except Exception as exc:
            normal_text = f"unavailable: {exc}"

        vertices = []
        for vertex in face.Vertices():
            point = vertex.Center()
            vertices.append((round(point.x, 6), round(point.y, 6), round(point.z, 6)))

        print(
            f"{face_id}: type={geom_type}, area={face.Area():.6f}, "
            f"center=({center.x:.6f}, {center.y:.6f}, {center.z:.6f}), "
            f"normal={normal_text}, "
            f"bbox=({fbb.xmin:.6f},{fbb.xmax:.6f}; "
            f"{fbb.ymin:.6f},{fbb.ymax:.6f}; "
            f"{fbb.zmin:.6f},{fbb.zmax:.6f}), vertices={vertices}"
        )

    target = faces_by_id.get("FACE 11")
    if target is not None:
        print(f"FACE 11 outer wire edges: {len(target.outerWire().Edges())}")
        for index, edge in enumerate(target.outerWire().Edges()):
            center = edge.Center()
            ebb = edge.BoundingBox()
            print(
                f"FACE 11 EDGE {index}: type={edge.geomType()}, "
                f"length={edge.Length():.6f}, "
                f"center=({center.x:.6f}, {center.y:.6f}, {center.z:.6f}), "
                f"bbox=({ebb.xmin:.6f},{ebb.xmax:.6f}; "
                f"{ebb.ymin:.6f},{ebb.ymax:.6f}; "
                f"{ebb.zmin:.6f},{ebb.zmax:.6f})"
            )

    return model