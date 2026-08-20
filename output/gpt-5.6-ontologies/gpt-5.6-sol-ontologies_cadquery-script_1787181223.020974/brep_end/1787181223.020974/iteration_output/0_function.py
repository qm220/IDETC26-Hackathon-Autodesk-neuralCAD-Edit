def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    bbox = shape.BoundingBox()
    print("MODEL INSPECTION")
    print(f"Valid: {shape.isValid()}")
    print(f"Volume: {shape.Volume():.6f} mm^3")
    print(f"Faces: {len(shape.Faces())}, Edges: {len(shape.Edges())}, Solids: {len(shape.Solids())}")
    print(f"BBox: x=({bbox.xmin:.6f}, {bbox.xmax:.6f}), y=({bbox.ymin:.6f}, {bbox.ymax:.6f}), z=({bbox.zmin:.6f}, {bbox.zmax:.6f})")
    print(f"BBox center: ({bbox.center.x:.6f}, {bbox.center.y:.6f}, {bbox.center.z:.6f})")

    for index, face in enumerate(shape.Faces()):
        center = face.Center()
        fb = face.BoundingBox()
        try:
            normal = face.normalAt()
            normal_text = f"({normal.x:.6f}, {normal.y:.6f}, {normal.z:.6f})"
        except Exception as exc:
            normal_text = f"unavailable: {exc}"
        try:
            geom_type = face.geomType()
        except Exception:
            geom_type = "UNKNOWN"
        print(
            f"FACE {index}: type={geom_type}, area={face.Area():.6f}, "
            f"center=({center.x:.6f}, {center.y:.6f}, {center.z:.6f}), "
            f"normal={normal_text}, "
            f"bbox=x({fb.xmin:.6f},{fb.xmax:.6f}) "
            f"y({fb.ymin:.6f},{fb.ymax:.6f}) z({fb.zmin:.6f},{fb.zmax:.6f}), "
            f"wires={len(face.Wires())}, edges={len(face.Edges())}"
        )

    return model