def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    print("=== Imported STEP inspection ===")
    print(f"Valid: {shape.isValid()}")
    print(f"Solids: {len(shape.Solids())}, Faces: {len(shape.Faces())}")
    bb = shape.BoundingBox()
    print(f"Assembly bbox: x=({bb.xmin:.3f},{bb.xmax:.3f}) y=({bb.ymin:.3f},{bb.ymax:.3f}) z=({bb.zmin:.3f},{bb.zmax:.3f})")

    solids = shape.Solids()
    for i, solid in enumerate(solids):
        sb = solid.BoundingBox()
        c = solid.Center()
        print(
            f"SOLID {i}: faces={len(solid.Faces())}, volume={solid.Volume():.3f}, "
            f"center=({c.x:.3f},{c.y:.3f},{c.z:.3f}), "
            f"bbox=x({sb.xmin:.3f},{sb.xmax:.3f}) "
            f"y({sb.ymin:.3f},{sb.ymax:.3f}) z({sb.zmin:.3f},{sb.zmax:.3f})"
        )

    # Bind the planning-stage FACE numbers to the actual imported geometry.
    faces = shape.Faces()
    inspect_indices = list(range(373, 414))
    print("=== R05 cord/plug global face bindings ===")
    for idx in inspect_indices:
        if idx >= len(faces):
            continue
        face = faces[idx]
        fb = face.BoundingBox()
        fc = face.Center()
        try:
            geom = face.geomType()
        except Exception:
            geom = "UNKNOWN"
        try:
            area = face.Area()
        except Exception:
            area = 0.0
        try:
            uv = face._geomAdaptor().Surface().Bounds()
        except Exception:
            uv = None
        print(
            f"FACE {idx}: type={geom}, area={area:.4f}, "
            f"center=({fc.x:.4f},{fc.y:.4f},{fc.z:.4f}), "
            f"bbox=x({fb.xmin:.4f},{fb.xmax:.4f}) "
            f"y({fb.ymin:.4f},{fb.ymax:.4f}) z({fb.zmin:.4f},{fb.zmax:.4f}), "
            f"edges={len(face.Edges())}, wires={len(face.Wires())}"
        )

    # More focused inspection of the existing terminal face and plug transition.
    for idx in [394, 398, 400, 403, 404, 405, 406, 407, 408, 409, 410, 411, 412, 413]:
        if idx >= len(faces):
            continue
        face = faces[idx]
        print(f"--- FACE {idx} edges ---")
        for j, edge in enumerate(face.Edges()):
            eb = edge.BoundingBox()
            ec = edge.Center()
            try:
                et = edge.geomType()
            except Exception:
                et = "UNKNOWN"
            print(
                f" edge {j}: type={et}, length={edge.Length():.4f}, "
                f"center=({ec.x:.4f},{ec.y:.4f},{ec.z:.4f}), "
                f"bbox=x({eb.xmin:.4f},{eb.xmax:.4f}) "
                f"y({eb.ymin:.4f},{eb.ymax:.4f}) z({eb.zmin:.4f},{eb.zmax:.4f})"
            )

    # Return the untouched model for the first-iteration reference rendering.
    return model