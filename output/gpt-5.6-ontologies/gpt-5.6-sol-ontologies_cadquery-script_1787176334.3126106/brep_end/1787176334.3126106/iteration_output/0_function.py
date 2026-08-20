def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    bbox = shape.BoundingBox()
    center = bbox.center
    print(f"Valid: {shape.isValid()}")
    print(f"Volume: {shape.Volume():.6f} mm^3")
    print(f"Faces: {len(shape.Faces())}, Edges: {len(shape.Edges())}, Solids: {len(shape.Solids())}")
    print(f"BBox: x=({bbox.xmin:.4f},{bbox.xmax:.4f}) y=({bbox.ymin:.4f},{bbox.ymax:.4f}) z=({bbox.zmin:.4f},{bbox.zmax:.4f})")
    print(f"BBox center: ({center.x:.4f},{center.y:.4f},{center.z:.4f})")

    for index, face in enumerate(shape.Faces()):
        fc = face.Center()
        fb = face.BoundingBox()
        try:
            geom_type = face.geomType()
        except Exception:
            geom_type = "UNKNOWN"
        try:
            normal = face.normalAt(fc)
            normal_text = f"({normal.x:.4f},{normal.y:.4f},{normal.z:.4f})"
        except Exception as exc:
            normal_text = f"unavailable:{exc}"
        print(
            f"FACE {index}: type={geom_type}, area={face.Area():.6f}, "
            f"center=({fc.x:.4f},{fc.y:.4f},{fc.z:.4f}), normal={normal_text}, "
            f"bbox=x({fb.xmin:.4f},{fb.xmax:.4f}) y({fb.ymin:.4f},{fb.ymax:.4f}) z({fb.zmin:.4f},{fb.zmax:.4f}), "
            f"edges={len(face.Edges())}"
        )

    for index, edge in enumerate(shape.Edges()):
        ec = edge.Center()
        eb = edge.BoundingBox()
        try:
            geom_type = edge.geomType()
        except Exception:
            geom_type = "UNKNOWN"
        try:
            length = edge.Length()
        except Exception:
            length = -1.0
        print(
            f"EDGE {index}: type={geom_type}, length={length:.6f}, "
            f"center=({ec.x:.4f},{ec.y:.4f},{ec.z:.4f}), "
            f"bbox=x({eb.xmin:.4f},{eb.xmax:.4f}) y({eb.ymin:.4f},{eb.ymax:.4f}) z({eb.zmin:.4f},{eb.zmax:.4f})"
        )

    return model