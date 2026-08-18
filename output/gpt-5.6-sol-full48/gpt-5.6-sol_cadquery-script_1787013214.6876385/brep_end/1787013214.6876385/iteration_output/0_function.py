def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    print(f"Model valid: {shape.isValid()}")
    print(f"Model solids: {len(shape.Solids())}, faces: {len(shape.Faces())}")
    bb = shape.BoundingBox()
    print(f"MODEL BBOX: x=({bb.xmin:.3f},{bb.xmax:.3f}) y=({bb.ymin:.3f},{bb.ymax:.3f}) z=({bb.zmin:.3f},{bb.zmax:.3f})")

    for i, solid in enumerate(shape.Solids()):
        sb = solid.BoundingBox()
        c = solid.Center()
        print(
            f"SOLID {i}: vol={solid.Volume():.3f}, faces={len(solid.Faces())}, "
            f"bbox=x({sb.xmin:.3f},{sb.xmax:.3f}) y({sb.ymin:.3f},{sb.ymax:.3f}) "
            f"z({sb.zmin:.3f},{sb.zmax:.3f}), center=({c.x:.3f},{c.y:.3f},{c.z:.3f})"
        )

    print("Candidate faces near the cartridge/handle region:")
    for i, face in enumerate(shape.Faces()):
        fb = face.BoundingBox()
        fc = face.Center()
        # Fusion event dimensions appear to be centimetres while STEP is likely millimetres.
        # Report faces centered in the corresponding internal upper region.
        if (-80.0 <= fc.x <= 80.0 and 20.0 <= fc.y <= 200.0 and -80.0 <= fc.z <= 120.0):
            try:
                geom = face.geomType()
            except Exception:
                geom = "UNKNOWN"
            print(
                f"FACE {i}: type={geom}, area={face.Area():.3f}, "
                f"bbox=x({fb.xmin:.3f},{fb.xmax:.3f}) y({fb.ymin:.3f},{fb.ymax:.3f}) "
                f"z({fb.zmin:.3f},{fb.zmax:.3f}), center=({fc.x:.3f},{fc.y:.3f},{fc.z:.3f})"
            )

    return model