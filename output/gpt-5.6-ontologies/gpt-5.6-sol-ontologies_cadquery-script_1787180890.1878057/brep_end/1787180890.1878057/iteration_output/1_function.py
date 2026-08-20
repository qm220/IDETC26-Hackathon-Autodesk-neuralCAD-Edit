def my_cad_function(args):
    import cadquery as cq
    import os

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)

    solids = model.solids().vals()
    print(f"Imported solids: {len(solids)}")
    if not solids:
        print("No solid was found in the imported STEP model.")
        return model

    shape = solids[0]
    print(f"Valid: {shape.isValid()}")
    try:
        print(f"Volume: {shape.Volume():.6f} mm^3")
    except Exception as exc:
        print(f"Volume unavailable: {exc}")

    bb = shape.BoundingBox()
    print(
        f"BBox: x=[{bb.xmin:.6f},{bb.xmax:.6f}] "
        f"y=[{bb.ymin:.6f},{bb.ymax:.6f}] "
        f"z=[{bb.zmin:.6f},{bb.zmax:.6f}]"
    )
    print(
        f"Faces: {len(shape.Faces())}, Edges: {len(shape.Edges())}, "
        f"Solids: {len(shape.Solids())}"
    )

    for i, face in enumerate(shape.Faces()):
        c = face.Center()
        fb = face.BoundingBox()
        geom = face.geomType()
        normal_text = "unavailable"
        try:
            n = face.normalAt(c)
            normal_text = f"({n.x:.6f},{n.y:.6f},{n.z:.6f})"
        except Exception:
            try:
                n = face.normalAt()
                normal_text = f"({n.x:.6f},{n.y:.6f},{n.z:.6f})"
            except Exception:
                pass

        print(
            f"FACE {i}: type={geom} area={face.Area():.6f} "
            f"center=({c.x:.6f},{c.y:.6f},{c.z:.6f}) "
            f"normal={normal_text} "
            f"bbox=([{fb.xmin:.3f},{fb.xmax:.3f}],"
            f"[{fb.ymin:.3f},{fb.ymax:.3f}],"
            f"[{fb.zmin:.3f},{fb.zmax:.3f}])"
        )

    return cq.Workplane(obj=shape)
