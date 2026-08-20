def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    root = model.val()

    print(f"Model valid: {root.isValid()}")
    print(f"Root type: {root.ShapeType()}")
    print(f"Total solids: {len(root.Solids())}")
    print(f"Total faces: {len(root.Faces())}")
    bb = root.BoundingBox()
    print(f"Model bbox: x=({bb.xmin:.4f},{bb.xmax:.4f}) y=({bb.ymin:.4f},{bb.ymax:.4f}) z=({bb.zmin:.4f},{bb.zmax:.4f})")
    print(f"Model center: ({bb.center.x:.4f},{bb.center.y:.4f},{bb.center.z:.4f})")

    for si, solid in enumerate(root.Solids()):
        sbb = solid.BoundingBox()
        print(f"\nSOLID {si}: valid={solid.isValid()} volume={solid.Volume():.6f} faces={len(solid.Faces())}")
        print(f"  bbox x=({sbb.xmin:.4f},{sbb.xmax:.4f}) y=({sbb.ymin:.4f},{sbb.ymax:.4f}) z=({sbb.zmin:.4f},{sbb.zmax:.4f})")
        for fi, face in enumerate(solid.Faces()):
            c = face.Center()
            fbb = face.BoundingBox()
            try:
                gt = face.geomType()
            except Exception:
                gt = "UNKNOWN"
            try:
                n = face.normalAt(c)
                normal_text = f"({n.x:.3f},{n.y:.3f},{n.z:.3f})"
            except Exception:
                normal_text = "n/a"
            radius_text = ""
            try:
                radius_text = f" radius={face.radius():.6f}"
            except Exception:
                pass
            print(
                f"  FACE {fi}: type={gt} area={face.Area():.6f} "
                f"center=({c.x:.4f},{c.y:.4f},{c.z:.4f}) normal={normal_text}{radius_text} "
                f"bbox=({fbb.xmin:.3f},{fbb.xmax:.3f}; {fbb.ymin:.3f},{fbb.ymax:.3f}; {fbb.zmin:.3f},{fbb.zmax:.3f}) "
                f"edges={len(face.Edges())}"
            )

    return model
