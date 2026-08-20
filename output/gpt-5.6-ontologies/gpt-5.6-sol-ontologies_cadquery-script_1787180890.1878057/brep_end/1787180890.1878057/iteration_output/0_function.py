def my_cad_function(args):
    import os
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    print(f"Valid: {shape.isValid()}")
    print(f"Volume: {shape.Volume():.6f} mm^3")
    bb = shape.BoundingBox()
    print(f"BBox: x=[{bb.xmin:.6f},{bb.xmax:.6f}] y=[{bb.ymin:.6f},{bb.ymax:.6f}] z=[{bb.zmin:.6f},{bb.zmax:.6f}]")
    print(f"Faces: {len(shape.Faces())}, Edges: {len(shape.Edges())}, Solids: {len(shape.Solids())}")

    for i, face in enumerate(shape.Faces()):
        c = face.Center()
        fb = face.BoundingBox()
        geom = face.geomType()
        try:
            n = face.normalAt(c)
            normal_text = f"({n.x:.6f},{n.y:.6f},{n.z:.6f})"
        except Exception:
            normal_text = "unavailable"
        verts = []
        for vertex in face.Vertices():
            p = vertex.Center()
            verts.append(f"({p.x:.3f},{p.y:.3f},{p.z:.3f})")
        print(
            f"FACE {i}: type={geom} area={face.Area():.6f} "
            f"center=({c.x:.6f},{c.y:.6f},{c.z:.6f}) normal={normal_text} "
            f"bbox=([{fb.xmin:.3f},{fb.xmax:.3f}],"
            f"[{fb.ymin:.3f},{fb.ymax:.3f}],"
            f"[{fb.zmin:.3f},{fb.zmax:.3f}]) "
            f"vertices={';'.join(verts)}"
        )

    for i, edge in enumerate(shape.Edges()):
        c = edge.Center()
        eb = edge.BoundingBox()
        print(
            f"EDGE {i}: type={edge.geomType()} length={edge.Length():.6f} "
            f"center=({c.x:.6f},{c.y:.6f},{c.z:.6f}) "
            f"bbox=([{eb.xmin:.3f},{eb.xmax:.3f}],"
            f"[{eb.ymin:.3f},{eb.ymax:.3f}],"
            f"[{eb.zmin:.3f},{eb.zmax:.3f}])"
        )

    return model