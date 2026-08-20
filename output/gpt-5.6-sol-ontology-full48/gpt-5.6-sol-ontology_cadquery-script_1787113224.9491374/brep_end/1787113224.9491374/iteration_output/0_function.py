def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    bbox = shape.BoundingBox()
    print("Loaded STEP model for rib-placement interrogation")
    print(f"Valid: {shape.isValid()}, solids: {len(shape.Solids())}, faces: {len(shape.Faces())}")
    print(f"Volume: {shape.Volume():.6f} mm^3")
    print(
        f"Model bbox: x=({bbox.xmin:.6f},{bbox.xmax:.6f}) "
        f"y=({bbox.ymin:.6f},{bbox.ymax:.6f}) "
        f"z=({bbox.zmin:.6f},{bbox.zmax:.6f})"
    )

    faces = shape.Faces()
    target_indices = {44, 46, 49, 50, 51, 52, 57, 66, 77, 78, 79, 89, 90, 92, 95, 100, 107}

    print("--- Grounded target faces ---")
    for i in sorted(target_indices):
        if i >= len(faces):
            print(f"FACE {i}: index unavailable")
            continue
        face = faces[i]
        fb = face.BoundingBox()
        c = face.Center()
        try:
            gt = face.geomType()
        except Exception:
            gt = "UNKNOWN"
        try:
            area = face.Area()
        except Exception:
            area = -1.0
        try:
            n = face.normalAt(c)
            normal_text = f" normal=({n.x:.6f},{n.y:.6f},{n.z:.6f})"
        except Exception:
            normal_text = ""
        print(
            f"FACE {i}: {gt} area={area:.6f} center=({c.x:.6f},{c.y:.6f},{c.z:.6f}) "
            f"bbox=x({fb.xmin:.6f},{fb.xmax:.6f}) y({fb.ymin:.6f},{fb.ymax:.6f}) "
            f"z({fb.zmin:.6f},{fb.zmax:.6f}){normal_text}"
        )
        print(f"  wires={len(face.Wires())}, edges={len(face.Edges())}")
        for j, edge in enumerate(face.Edges()):
            eb = edge.BoundingBox()
            ec = edge.Center()
            try:
                et = edge.geomType()
            except Exception:
                et = "UNKNOWN"
            print(
                f"    edge {j}: {et} center=({ec.x:.6f},{ec.y:.6f},{ec.z:.6f}) "
                f"bbox=x({eb.xmin:.6f},{eb.xmax:.6f}) y({eb.ymin:.6f},{eb.ymax:.6f}) "
                f"z({eb.zmin:.6f},{eb.zmax:.6f})"
            )

    print("--- All face summary for actual STEP index binding ---")
    for i, face in enumerate(faces):
        fb = face.BoundingBox()
        c = face.Center()
        try:
            gt = face.geomType()
        except Exception:
            gt = "UNKNOWN"
        print(
            f"FACE {i}: {gt} A={face.Area():.5f} C=({c.x:.4f},{c.y:.4f},{c.z:.4f}) "
            f"B=({fb.xmin:.4f},{fb.xmax:.4f};{fb.ymin:.4f},{fb.ymax:.4f};{fb.zmin:.4f},{fb.zmax:.4f})"
        )

    # This interrogation pass intentionally preserves the starting solid. The printed
    # topology will be used to place and trim the exact 1.5 mm rib on the next pass.
    return model