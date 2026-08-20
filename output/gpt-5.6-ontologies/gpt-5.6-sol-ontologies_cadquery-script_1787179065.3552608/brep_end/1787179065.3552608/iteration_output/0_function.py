def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    print("=== LOADED MODEL ===")
    print(f"Valid: {shape.isValid()}")
    bb = shape.BoundingBox()
    print(f"Overall bbox: x=({bb.xmin:.3f},{bb.xmax:.3f}) y=({bb.ymin:.3f},{bb.ymax:.3f}) z=({bb.zmin:.3f},{bb.zmax:.3f})")

    solids = shape.Solids()
    print(f"Solids: {len(solids)}")
    for i, solid in enumerate(solids):
        sb = solid.BoundingBox()
        sc = sb.center
        print(
            f"SOLID {i}: volume={solid.Volume():.3f}, faces={len(solid.Faces())}, "
            f"center=({sc.x:.3f},{sc.y:.3f},{sc.z:.3f}), "
            f"bbox=x({sb.xmin:.3f},{sb.xmax:.3f}) "
            f"y({sb.ymin:.3f},{sb.ymax:.3f}) z({sb.zmin:.3f},{sb.zmax:.3f})"
        )

    faces = shape.Faces()
    print(f"Global faces: {len(faces)}")
    print("=== GROUNDED F015/F016 INTERFACE AND PLUG FACES ===")
    for i in range(373, min(414, len(faces))):
        face = faces[i]
        fc = face.Center()
        fb = face.BoundingBox()
        try:
            kind = face.geomType()
        except Exception:
            kind = "UNKNOWN"
        try:
            normal = face.normalAt(fc)
            normal_text = f"({normal.x:.3f},{normal.y:.3f},{normal.z:.3f})"
        except Exception:
            normal_text = "n/a"
        print(
            f"FACE {i}: type={kind}, area={face.Area():.3f}, "
            f"center=({fc.x:.3f},{fc.y:.3f},{fc.z:.3f}), normal={normal_text}, "
            f"bbox=x({fb.xmin:.3f},{fb.xmax:.3f}) "
            f"y({fb.ymin:.3f},{fb.ymax:.3f}) z({fb.zmin:.3f},{fb.zmax:.3f})"
        )

    print("=== TARGET SOLID VERTICES ===")
    for solid_index in (18, 19):
        if solid_index >= len(solids):
            continue
        vertices = solids[solid_index].Vertices()
        print(f"SOLID {solid_index} vertices={len(vertices)}")
        for j, vertex in enumerate(vertices):
            p = vertex.Center()
            print(f"  V{j}: ({p.x:.3f},{p.y:.3f},{p.z:.3f})")

    return model