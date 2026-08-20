def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    print(f"MODEL valid={shape.isValid()} type={shape.ShapeType()}")
    bb = shape.BoundingBox()
    print(f"MODEL bbox=({bb.xmin:.3f},{bb.ymin:.3f},{bb.zmin:.3f}) to ({bb.xmax:.3f},{bb.ymax:.3f},{bb.zmax:.3f})")

    solids = shape.Solids()
    print(f"SOLID COUNT: {len(solids)}")
    for i, solid in enumerate(solids):
        sb = solid.BoundingBox()
        sc = solid.Center()
        print(
            f"SOLID {i}: volume={solid.Volume():.3f} faces={len(solid.Faces())} "
            f"center=({sc.x:.3f},{sc.y:.3f},{sc.z:.3f}) "
            f"bbox=({sb.xmin:.3f},{sb.ymin:.3f},{sb.zmin:.3f})-"
            f"({sb.xmax:.3f},{sb.ymax:.3f},{sb.zmax:.3f})"
        )

    faces = shape.Faces()
    print(f"GLOBAL FACE COUNT: {len(faces)}")
    print("F001 / SOLID 0 candidate faces (global FACE 0 through FACE 71):")
    for i, face in enumerate(faces[:72]):
        fc = face.Center()
        fb = face.BoundingBox()
        geom = face.geomType()
        normal_text = ""
        try:
            n = face.normalAt()
            normal_text = f" normal=({n.x:.3f},{n.y:.3f},{n.z:.3f})"
        except Exception:
            pass
        print(
            f"FACE {i}: type={geom} area={face.Area():.3f} "
            f"center=({fc.x:.3f},{fc.y:.3f},{fc.z:.3f}){normal_text} "
            f"bbox=({fb.xmin:.3f},{fb.ymin:.3f},{fb.zmin:.3f})-"
            f"({fb.xmax:.3f},{fb.ymax:.3f},{fb.zmax:.3f})"
        )

    return model