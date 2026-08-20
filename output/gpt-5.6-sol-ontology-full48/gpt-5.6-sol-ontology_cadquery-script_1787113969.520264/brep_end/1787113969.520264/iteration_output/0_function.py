def my_cad_function(args):
    import os
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    print("=== MODEL INSPECTION ===")
    print(f"Valid: {shape.isValid()}")
    print(f"Solids: {len(shape.Solids())}, Faces: {len(shape.Faces())}, Volume: {shape.Volume():.6f}")
    bb = shape.BoundingBox()
    print(f"Model bbox: x=[{bb.xmin:.4f},{bb.xmax:.4f}] y=[{bb.ymin:.4f},{bb.ymax:.4f}] z=[{bb.zmin:.4f},{bb.zmax:.4f}]")

    for si, solid in enumerate(shape.Solids()):
        sb = solid.BoundingBox()
        print(f"SOLID {si}: faces={len(solid.Faces())}, volume={solid.Volume():.6f}, bbox=x[{sb.xmin:.4f},{sb.xmax:.4f}] y[{sb.ymin:.4f},{sb.ymax:.4f}] z[{sb.zmin:.4f},{sb.zmax:.4f}]")

    faces = shape.Faces()

    def describe_face(index):
        if index < 0 or index >= len(faces):
            print(f"FACE {index}: out of range")
            return
        f = faces[index]
        fb = f.BoundingBox()
        c = f.Center()
        try:
            gt = f.geomType()
        except Exception:
            gt = "UNKNOWN"
        try:
            n = f.normalAt(c)
            normal_text = f"({n.x:.4f},{n.y:.4f},{n.z:.4f})"
        except Exception:
            normal_text = "n/a"
        print(
            f"FACE {index}: type={gt}, area={f.Area():.6f}, center=({c.x:.4f},{c.y:.4f},{c.z:.4f}), "
            f"normal={normal_text}, wires={len(f.Wires())}, edges={len(f.Edges())}, "
            f"bbox=x[{fb.xmin:.4f},{fb.xmax:.4f}] y[{fb.ymin:.4f},{fb.ymax:.4f}] z[{fb.zmin:.4f},{fb.zmax:.4f}]"
        )

    print("=== GROUNDED TARGET FACES ===")
    for idx in [0, 1, 2, 3, 4, 147, 223, 224, 225, 226, 227, 228, 229, 230, 231, 232, 233, 496, 497, 668, 669]:
        describe_face(idx)

    print("=== CENTRAL FACES IN CARRIER RANGE 497-669 ===")
    for idx in range(497, min(670, len(faces))):
        f = faces[idx]
        fb = f.BoundingBox()
        radial_extent = max(abs(fb.xmin), abs(fb.xmax), abs(fb.zmin), abs(fb.zmax))
        if radial_extent <= 23.0:
            describe_face(idx)

    print("=== INSERT FACE 1 BOUNDARY EDGES ===")
    if len(faces) > 1:
        for ei, edge in enumerate(faces[1].Edges()):
            eb = edge.BoundingBox()
            ec = edge.Center()
            try:
                et = edge.geomType()
            except Exception:
                et = "UNKNOWN"
            print(f"FACE 1 EDGE {ei}: type={et}, length={edge.Length():.6f}, center=({ec.x:.4f},{ec.y:.4f},{ec.z:.4f}), bbox=x[{eb.xmin:.4f},{eb.xmax:.4f}] y[{eb.ymin:.4f},{eb.ymax:.4f}] z[{eb.zmin:.4f},{eb.zmax:.4f}]")

    return model