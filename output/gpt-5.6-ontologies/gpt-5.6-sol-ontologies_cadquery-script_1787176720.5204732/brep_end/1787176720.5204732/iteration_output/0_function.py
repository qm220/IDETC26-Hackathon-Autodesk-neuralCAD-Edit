def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    print("=== MODEL INSPECTION ===")
    print(f"Valid: {shape.isValid()}")
    bb = shape.BoundingBox()
    print(f"Model bbox: x=({bb.xmin:.4f},{bb.xmax:.4f}) y=({bb.ymin:.4f},{bb.ymax:.4f}) z=({bb.zmin:.4f},{bb.zmax:.4f})")
    print(f"Model center: ({bb.center.x:.4f},{bb.center.y:.4f},{bb.center.z:.4f})")
    print(f"Solids: {len(shape.Solids())}, Faces: {len(shape.Faces())}, Edges: {len(shape.Edges())}")

    for si, solid in enumerate(shape.Solids()):
        sb = solid.BoundingBox()
        sc = solid.Center()
        print(f"SOLID {si}: volume={solid.Volume():.6f}, center=({sc.x:.4f},{sc.y:.4f},{sc.z:.4f}), bbox=x({sb.xmin:.4f},{sb.xmax:.4f}) y({sb.ymin:.4f},{sb.ymax:.4f}) z({sb.zmin:.4f},{sb.zmax:.4f}), faces={len(solid.Faces())}")
        edge_lengths = sorted([e.Length() for e in solid.Edges()], reverse=True)
        print(f"  longest edges: {[round(v,4) for v in edge_lengths[:16]]}")

    print("=== GLOBAL FACE INDEX BINDING ===")
    for i, face in enumerate(shape.Faces()):
        c = face.Center()
        fb = face.BoundingBox()
        try:
            geom = face.geomType()
        except Exception:
            geom = "UNKNOWN"
        try:
            n = face.normalAt(c)
            normal_text = f"({n.x:.4f},{n.y:.4f},{n.z:.4f})"
        except Exception:
            normal_text = "n/a"
        print(f"FACE {i}: type={geom}, area={face.Area():.5f}, center=({c.x:.4f},{c.y:.4f},{c.z:.4f}), normal={normal_text}, bbox=x({fb.xmin:.4f},{fb.xmax:.4f}) y({fb.ymin:.4f},{fb.ymax:.4f}) z({fb.zmin:.4f},{fb.zmax:.4f}), edges={len(face.Edges())}")

    return model