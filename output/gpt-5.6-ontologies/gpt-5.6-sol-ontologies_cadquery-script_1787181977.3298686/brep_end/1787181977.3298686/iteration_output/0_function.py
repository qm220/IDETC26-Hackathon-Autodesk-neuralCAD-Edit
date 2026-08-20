def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    bbox = shape.BoundingBox()
    print(f"VALID={shape.isValid()} VOLUME={shape.Volume():.6f}")
    print(f"BBOX x=({bbox.xmin:.6f},{bbox.xmax:.6f}) y=({bbox.ymin:.6f},{bbox.ymax:.6f}) z=({bbox.zmin:.6f},{bbox.zmax:.6f})")
    print(f"SOLIDS={len(shape.Solids())} FACES={len(shape.Faces())} EDGES={len(shape.Edges())}")

    for i, face in enumerate(shape.Faces()):
        c = face.Center()
        fb = face.BoundingBox()
        try:
            geom_type = face.geomType()
        except Exception:
            geom_type = "UNKNOWN"
        try:
            n = face.normalAt(c)
            normal_text = f"({n.x:.5f},{n.y:.5f},{n.z:.5f})"
        except Exception:
            normal_text = "n/a"
        try:
            area = face.Area()
        except Exception:
            area = -1.0
        print(
            f"FACE {i}: type={geom_type} area={area:.6f} "
            f"center=({c.x:.6f},{c.y:.6f},{c.z:.6f}) normal={normal_text} "
            f"bbox=({fb.xmin:.6f},{fb.xmax:.6f}; {fb.ymin:.6f},{fb.ymax:.6f}; {fb.zmin:.6f},{fb.zmax:.6f}) "
            f"edges={len(face.Edges())}"
        )

    for i, edge in enumerate(shape.Edges()):
        c = edge.Center()
        eb = edge.BoundingBox()
        try:
            geom_type = edge.geomType()
        except Exception:
            geom_type = "UNKNOWN"
        try:
            length = edge.Length()
        except Exception:
            length = -1.0
        try:
            radius = edge.radius()
            radius_text = f"{radius:.6f}"
        except Exception:
            radius_text = "n/a"
        print(
            f"EDGE {i}: type={geom_type} length={length:.6f} radius={radius_text} "
            f"center=({c.x:.6f},{c.y:.6f},{c.z:.6f}) "
            f"bbox=({eb.xmin:.6f},{eb.xmax:.6f}; {eb.ymin:.6f},{eb.ymax:.6f}; {eb.zmin:.6f},{eb.zmax:.6f})"
        )

    return model