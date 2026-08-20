def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    model = imported.val() if hasattr(imported, "val") else imported

    solids = model.Solids()
    faces = model.Faces()
    print(f"Model valid: {model.isValid()}")
    print(f"Solid count: {len(solids)}; global face count: {len(faces)}")

    for i, solid in enumerate(solids):
        bb = solid.BoundingBox()
        c = bb.center
        print(
            f"SOLID {i}: volume={solid.Volume():.6f}, "
            f"bbox=({bb.xmin:.6f},{bb.ymin:.6f},{bb.zmin:.6f}) to "
            f"({bb.xmax:.6f},{bb.ymax:.6f},{bb.zmax:.6f}), "
            f"center=({c.x:.6f},{c.y:.6f},{c.z:.6f}), faces={len(solid.Faces())}"
        )

    target_face_indices = [1, 3, 40, 41, 42, 43, 44, 361, 362, 365, 366, 368, 370]
    for idx in target_face_indices:
        if idx >= len(faces):
            print(f"FACE {idx}: index unavailable")
            continue
        face = faces[idx]
        bb = face.BoundingBox()
        c = face.Center()
        try:
            geom = face.geomType()
        except Exception:
            geom = "UNKNOWN"
        print(
            f"FACE {idx}: type={geom}, area={face.Area():.6f}, "
            f"center=({c.x:.6f},{c.y:.6f},{c.z:.6f}), "
            f"bbox=({bb.xmin:.6f},{bb.ymin:.6f},{bb.zmin:.6f}) to "
            f"({bb.xmax:.6f},{bb.ymax:.6f},{bb.zmax:.6f})"
        )

    if len(solids) > 17:
        housing = solids[0]
        cradle = solids[17]
        try:
            common = housing.intersect(cradle)
            common_volume = common.Volume() if common is not None else 0.0
            print(f"Initial SOLID 0 / SOLID 17 common volume: {common_volume:.9f} mm^3")
            if common is not None and common_volume > 1.0e-8:
                bb = common.BoundingBox()
                print(
                    f"Interference bbox=({bb.xmin:.6f},{bb.ymin:.6f},{bb.zmin:.6f}) to "
                    f"({bb.xmax:.6f},{bb.ymax:.6f},{bb.zmax:.6f})"
                )
        except Exception as exc:
            print(f"Unable to compute initial interference: {exc}")

    # First-pass diagnostic output intentionally preserves the source assembly.
    return imported