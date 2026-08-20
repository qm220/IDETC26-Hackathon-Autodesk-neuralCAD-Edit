def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    print("=== MODEL INSPECTION ===")
    print(f"Valid: {shape.isValid()}")
    print(f"Solids: {len(shape.Solids())}, Faces: {len(shape.Faces())}")
    bb = shape.BoundingBox()
    print(f"Model bbox: x=({bb.xmin:.3f},{bb.xmax:.3f}) y=({bb.ymin:.3f},{bb.ymax:.3f}) z=({bb.zmin:.3f},{bb.zmax:.3f})")

    # STEP-analysis face indices associated with the six pivot-pin features.
    terminal_ids = [31, 33, 34, 36, 39, 41, 122, 124, 127, 129, 217, 219]
    shaft_ids = [30, 35, 38, 121, 126, 218]
    faces = shape.Faces()

    print("=== GROUNDED PIN FACES ===")
    for i in terminal_ids + shaft_ids:
        if i >= len(faces):
            print(f"FACE {i}: OUT OF RANGE")
            continue
        f = faces[i]
        c = f.Center()
        fb = f.BoundingBox()
        try:
            n = f.normalAt(c)
            normal_text = f"({n.x:.4f},{n.y:.4f},{n.z:.4f})"
        except Exception as exc:
            normal_text = f"unavailable: {exc}"
        print(
            f"FACE {i}: type={f.geomType()} area={f.Area():.5f} "
            f"center=({c.x:.4f},{c.y:.4f},{c.z:.4f}) normal={normal_text} "
            f"bbox=({fb.xmin:.4f},{fb.xmax:.4f}; {fb.ymin:.4f},{fb.ymax:.4f}; {fb.zmin:.4f},{fb.zmax:.4f})"
        )

    print("=== SOLID INSPECTION ===")
    for si, solid in enumerate(shape.Solids()):
        sb = solid.BoundingBox()
        sc = solid.Center()
        dims = (sb.xlen, sb.ylen, sb.zlen)
        print(
            f"SOLID {si}: volume={solid.Volume():.5f} center=({sc.x:.4f},{sc.y:.4f},{sc.z:.4f}) "
            f"dims=({dims[0]:.4f},{dims[1]:.4f},{dims[2]:.4f}) faces={len(solid.Faces())}"
        )
        # Pin solids are expected to have very few faces. Print their topology in detail.
        if len(solid.Faces()) <= 6:
            for j, f in enumerate(solid.Faces()):
                c = f.Center()
                fb = f.BoundingBox()
                print(
                    f"  local face {j}: type={f.geomType()} area={f.Area():.5f} "
                    f"center=({c.x:.4f},{c.y:.4f},{c.z:.4f}) "
                    f"dims=({fb.xlen:.4f},{fb.ylen:.4f},{fb.zlen:.4f})"
                )

    # Return the unmodified model for the mandatory first inspection iteration.
    return model