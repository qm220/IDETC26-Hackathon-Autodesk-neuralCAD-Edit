def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    print(f"Loaded STEP: {input_file}")
    print(f"Valid: {shape.isValid()}")
    print(f"Solids: {len(shape.Solids())}, Faces: {len(shape.Faces())}, Edges: {len(shape.Edges())}")
    bb = shape.BoundingBox()
    print(
        f"Part bbox: x=({bb.xmin:.6f},{bb.xmax:.6f}) "
        f"y=({bb.ymin:.6f},{bb.ymax:.6f}) "
        f"z=({bb.zmin:.6f},{bb.zmax:.6f}); "
        f"size=({bb.xlen:.6f},{bb.ylen:.6f},{bb.zlen:.6f})"
    )

    for i, face in enumerate(shape.Faces()):
        c = face.Center()
        fb = face.BoundingBox()
        geom = face.geomType()
        try:
            n = face.normalAt(c)
            normal_text = f"({n.x:.6f},{n.y:.6f},{n.z:.6f})"
        except Exception:
            normal_text = "unavailable"
        print(
            f"FACE {i}: type={geom}, area={face.Area():.6f}, "
            f"center=({c.x:.6f},{c.y:.6f},{c.z:.6f}), normal={normal_text}, "
            f"bbox=({fb.xmin:.6f},{fb.xmax:.6f}; "
            f"{fb.ymin:.6f},{fb.ymax:.6f}; {fb.zmin:.6f},{fb.zmax:.6f})"
        )

    for i, edge in enumerate(shape.Edges()):
        c = edge.Center()
        eb = edge.BoundingBox()
        try:
            length = edge.Length()
        except Exception:
            length = -1.0
        print(
            f"EDGE {i}: type={edge.geomType()}, length={length:.6f}, "
            f"center=({c.x:.6f},{c.y:.6f},{c.z:.6f}), "
            f"bbox=({eb.xmin:.6f},{eb.xmax:.6f}; "
            f"{eb.ymin:.6f},{eb.ymax:.6f}; {eb.zmin:.6f},{eb.zmax:.6f})"
        )

    # Inspection iteration: return the unmodified source model so its orientation
    # and analyzed FACE indices can be checked before applying grounded edits.
    return model