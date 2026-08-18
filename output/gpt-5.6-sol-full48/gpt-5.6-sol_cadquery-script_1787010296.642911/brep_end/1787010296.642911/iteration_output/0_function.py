def my_cad_function(args):
    import os
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    print("=== INPUT MODEL INSPECTION ===")
    print(f"Valid: {shape.isValid()}")
    bb = shape.BoundingBox()
    print(f"Overall bbox: x=({bb.xmin:.4f},{bb.xmax:.4f}) y=({bb.ymin:.4f},{bb.ymax:.4f}) z=({bb.zmin:.4f},{bb.zmax:.4f})")
    print(f"Overall size: ({bb.xlen:.4f}, {bb.ylen:.4f}, {bb.zlen:.4f})")
    print(f"Overall center: ({bb.center.x:.4f}, {bb.center.y:.4f}, {bb.center.z:.4f})")
    print(f"Faces: {len(shape.Faces())}; Solids: {len(shape.Solids())}; Volume: {shape.Volume():.4f}")

    for i, solid in enumerate(shape.Solids()):
        sb = solid.BoundingBox()
        c = solid.Center()
        print(
            f"SOLID {i}: volume={solid.Volume():.4f}; "
            f"bbox=({sb.xmin:.4f},{sb.xmax:.4f}) x "
            f"({sb.ymin:.4f},{sb.ymax:.4f}) x "
            f"({sb.zmin:.4f},{sb.zmax:.4f}); "
            f"size=({sb.xlen:.4f},{sb.ylen:.4f},{sb.zlen:.4f}); "
            f"center=({c.x:.4f},{c.y:.4f},{c.z:.4f}); faces={len(solid.Faces())}"
        )

    print("=== CENTRAL/PLANAR FACE CANDIDATES ===")
    for i, face in enumerate(shape.Faces()):
        fb = face.BoundingBox()
        fc = face.Center()
        if abs(fc.x) < 20 and abs(fc.z) < 20:
            try:
                geom = face.geomType()
            except Exception:
                geom = "UNKNOWN"
            print(
                f"FACE {i}: type={geom}; area={face.Area():.4f}; "
                f"center=({fc.x:.4f},{fc.y:.4f},{fc.z:.4f}); "
                f"size=({fb.xlen:.4f},{fb.ylen:.4f},{fb.zlen:.4f})"
            )

    return model