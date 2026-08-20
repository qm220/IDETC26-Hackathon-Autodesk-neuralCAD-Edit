def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    print(f"Loaded: {input_file}")
    print(f"Valid: {shape.isValid()}")
    print(f"Volume: {shape.Volume():.6f}")
    print(f"Solids: {len(shape.Solids())}, Faces: {len(shape.Faces())}")

    bb = shape.BoundingBox()
    print(
        f"Overall bbox: x=({bb.xmin:.4f},{bb.xmax:.4f}) "
        f"y=({bb.ymin:.4f},{bb.ymax:.4f}) "
        f"z=({bb.zmin:.4f},{bb.zmax:.4f})"
    )

    solids = shape.Solids()
    global_faces = shape.Faces()

    for si, solid in enumerate(solids):
        sb = solid.BoundingBox()
        print(
            f"SOLID {si}: volume={solid.Volume():.6f}, faces={len(solid.Faces())}, "
            f"bbox=x({sb.xmin:.4f},{sb.xmax:.4f}) "
            f"y({sb.ymin:.4f},{sb.ymax:.4f}) "
            f"z({sb.zmin:.4f},{sb.zmax:.4f})"
        )

    print("Grounded target-face inspection:")
    for fi in (62, 101):
        face = global_faces[fi]
        c = face.Center()
        fb = face.BoundingBox()
        try:
            n = face.normalAt(c)
            normal_text = f"({n.x:.5f},{n.y:.5f},{n.z:.5f})"
        except Exception as exc:
            normal_text = f"unavailable: {exc}"
        owner = None
        for si, solid in enumerate(solids):
            if any(face.isSame(sf) for sf in solid.Faces()):
                owner = si
                break
        print(
            f"FACE {fi}: owner=SOLID {owner}, type={face.geomType()}, "
            f"area={face.Area():.6f}, center=({c.x:.4f},{c.y:.4f},{c.z:.4f}), "
            f"normal={normal_text}, bbox=x({fb.xmin:.4f},{fb.xmax:.4f}) "
            f"y({fb.ymin:.4f},{fb.ymax:.4f}) z({fb.zmin:.4f},{fb.zmax:.4f})"
        )

    for target_si in (4, 5):
        if target_si >= len(solids):
            continue
        print(f"Detailed faces for planned SOLID {target_si}:")
        solid = solids[target_si]
        for local_i, face in enumerate(solid.Faces()):
            global_i = None
            for gi, gf in enumerate(global_faces):
                if face.isSame(gf):
                    global_i = gi
                    break
            c = face.Center()
            fb = face.BoundingBox()
            try:
                n = face.normalAt(c)
                normal_text = f"({n.x:.3f},{n.y:.3f},{n.z:.3f})"
            except Exception:
                normal_text = "n/a"
            print(
                f"  local={local_i}, global={global_i}, type={face.geomType()}, "
                f"area={face.Area():.4f}, center=({c.x:.3f},{c.y:.3f},{c.z:.3f}), "
                f"normal={normal_text}, bbox=x({fb.xmin:.3f},{fb.xmax:.3f}) "
                f"y({fb.ymin:.3f},{fb.ymax:.3f}) z({fb.zmin:.3f},{fb.zmax:.3f})"
            )

    return model