def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    print(f"Model valid: {shape.isValid()}")
    print(f"Model type: {shape.ShapeType()}")
    print(f"Faces: {len(shape.Faces())}, solids: {len(shape.Solids())}")
    bb = shape.BoundingBox()
    print(f"MODEL bbox=({bb.xmin:.4f},{bb.ymin:.4f},{bb.zmin:.4f}) to ({bb.xmax:.4f},{bb.ymax:.4f},{bb.zmax:.4f}); size=({bb.xlen:.4f},{bb.ylen:.4f},{bb.zlen:.4f})")

    for i, solid in enumerate(shape.Solids()):
        sb = solid.BoundingBox()
        c = solid.Center()
        print(f"SOLID {i}: volume={solid.Volume():.4f}, faces={len(solid.Faces())}, center=({c.x:.4f},{c.y:.4f},{c.z:.4f}), bbox=({sb.xmin:.4f},{sb.ymin:.4f},{sb.zmin:.4f}) to ({sb.xmax:.4f},{sb.ymax:.4f},{sb.zmax:.4f})")

    target_ids = [0, 1, 2, 667, 668, 669, 670, 671, 672, 673, 778, 833, 834, 941, 1159, 1481]
    faces = shape.Faces()
    for i in target_ids:
        if i >= len(faces):
            continue
        f = faces[i]
        c = f.Center()
        fb = f.BoundingBox()
        try:
            gt = f.geomType()
        except Exception:
            gt = "UNKNOWN"
        try:
            area = f.Area()
        except Exception:
            area = -1
        edge_data = []
        for e in f.Edges():
            ec = e.Center()
            edge_data.append(f"{e.geomType()} L={e.Length():.3f} C=({ec.x:.2f},{ec.y:.2f},{ec.z:.2f})")
        print(f"FACE {i}: type={gt}, area={area:.4f}, center=({c.x:.4f},{c.y:.4f},{c.z:.4f}), bbox=({fb.xmin:.4f},{fb.ymin:.4f},{fb.zmin:.4f}) to ({fb.xmax:.4f},{fb.ymax:.4f},{fb.zmax:.4f}), edges=[{' | '.join(edge_data)}]")

    # Also report the largest planar faces, useful for resolving the gear axis and face width.
    planar = []
    for i, f in enumerate(faces):
        try:
            if f.geomType() == "PLANE":
                planar.append((f.Area(), i, f))
        except Exception:
            pass
    planar.sort(key=lambda item: item[0], reverse=True)
    for area, i, f in planar[:15]:
        c = f.Center()
        fb = f.BoundingBox()
        try:
            n = f.normalAt()
            ns = f"({n.x:.4f},{n.y:.4f},{n.z:.4f})"
        except Exception:
            ns = "unknown"
        print(f"LARGE PLANE FACE {i}: area={area:.4f}, center=({c.x:.4f},{c.y:.4f},{c.z:.4f}), normal={ns}, bbox=({fb.xmin:.3f},{fb.ymin:.3f},{fb.zmin:.3f}) to ({fb.xmax:.3f},{fb.ymax:.3f},{fb.zmax:.3f})")

    return model