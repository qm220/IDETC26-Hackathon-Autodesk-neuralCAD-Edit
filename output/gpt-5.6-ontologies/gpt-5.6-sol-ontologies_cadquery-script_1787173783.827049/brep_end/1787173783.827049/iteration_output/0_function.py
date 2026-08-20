def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    print(f"Loaded STEP: {input_file}")
    print(f"Valid: {shape.isValid()}")
    bbox = shape.BoundingBox()
    print(f"Overall bbox: x=({bbox.xmin:.3f}, {bbox.xmax:.3f}) y=({bbox.ymin:.3f}, {bbox.ymax:.3f}) z=({bbox.zmin:.3f}, {bbox.zmax:.3f})")
    print(f"Overall size: ({bbox.xlen:.3f}, {bbox.ylen:.3f}, {bbox.zlen:.3f})")

    solids = shape.Solids()
    faces = shape.Faces()
    print(f"Solids: {len(solids)}, Faces: {len(faces)}")

    for si, solid in enumerate(solids):
        sb = solid.BoundingBox()
        sc = solid.Center()
        print(
            f"SOLID {si}: volume={solid.Volume():.3f}, "
            f"center=({sc.x:.3f},{sc.y:.3f},{sc.z:.3f}), "
            f"bbox=x({sb.xmin:.3f},{sb.xmax:.3f}) "
            f"y({sb.ymin:.3f},{sb.ymax:.3f}) "
            f"z({sb.zmin:.3f},{sb.zmax:.3f}), faces={len(solid.Faces())}"
        )

    for fi, face in enumerate(faces):
        c = face.Center()
        fb = face.BoundingBox()
        geom = face.geomType()
        normal_text = "unavailable"
        try:
            n = face.normalAt(c)
            normal_text = f"({n.x:.3f},{n.y:.3f},{n.z:.3f})"
        except Exception:
            try:
                n = face.normalAt()
                normal_text = f"({n.x:.3f},{n.y:.3f},{n.z:.3f})"
            except Exception:
                pass
        print(
            f"FACE {fi}: type={geom}, area={face.Area():.3f}, "
            f"center=({c.x:.3f},{c.y:.3f},{c.z:.3f}), normal={normal_text}, "
            f"bbox=x({fb.xmin:.3f},{fb.xmax:.3f}) "
            f"y({fb.ymin:.3f},{fb.ymax:.3f}) "
            f"z({fb.zmin:.3f},{fb.zmax:.3f}), edges={len(face.Edges())}"
        )

    # Return the unchanged model for this inspection iteration.
    return model
