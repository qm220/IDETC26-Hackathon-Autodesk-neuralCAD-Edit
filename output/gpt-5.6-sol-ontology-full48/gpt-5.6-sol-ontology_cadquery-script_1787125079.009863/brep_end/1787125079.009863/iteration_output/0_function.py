def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    print("=== START MODEL INSPECTION ===")
    print(f"Valid: {shape.isValid()}")
    print(f"Solids: {len(shape.Solids())}, Faces: {len(shape.Faces())}, Edges: {len(shape.Edges())}")
    bb = shape.BoundingBox()
    print(f"Bounding box: x={bb.xmin:.6f}..{bb.xmax:.6f}, y={bb.ymin:.6f}..{bb.ymax:.6f}, z={bb.zmin:.6f}..{bb.zmax:.6f}")

    faces = shape.Faces()
    for i, face in enumerate(faces):
        fbb = face.BoundingBox()
        c = face.Center()
        try:
            gt = face.geomType()
        except Exception:
            gt = "UNKNOWN"
        print(
            f"FACE {i}: type={gt}, area={face.Area():.6f}, "
            f"center=({c.x:.6f},{c.y:.6f},{c.z:.6f}), "
            f"bbox=({fbb.xmin:.6f}..{fbb.xmax:.6f}, "
            f"{fbb.ymin:.6f}..{fbb.ymax:.6f}, "
            f"{fbb.zmin:.6f}..{fbb.zmax:.6f}), edges={len(face.Edges())}"
        )

    # Bind the planning FACE numbers to the imported STEP topology and inspect
    # the enlarged grip's +Y planar wall and all adjacent boundary topology.
    target_face_ids = [10, 31, 32, 34]
    for face_id in target_face_ids:
        if face_id >= len(faces):
            continue
        face = faces[face_id]
        print(f"--- Detailed edges of FACE {face_id} ({face.geomType()}) ---")
        for j, edge in enumerate(face.Edges()):
            ebb = edge.BoundingBox()
            c = edge.Center()
            try:
                gt = edge.geomType()
            except Exception:
                gt = "UNKNOWN"
            adjacent = []
            for k, other_face in enumerate(faces):
                if k == face_id:
                    continue
                if any(edge.isSame(other_edge) for other_edge in other_face.Edges()):
                    adjacent.append(k)
            print(
                f"FACE {face_id} EDGE {j}: type={gt}, length={edge.Length():.6f}, "
                f"center=({c.x:.6f},{c.y:.6f},{c.z:.6f}), "
                f"bbox=({ebb.xmin:.6f}..{ebb.xmax:.6f}, "
                f"{ebb.ymin:.6f}..{ebb.ymax:.6f}, "
                f"{ebb.zmin:.6f}..{ebb.zmax:.6f}), adjacent_faces={adjacent}"
            )

    # Also list global edges in R02 near the semantic-left (+Y) side. These are
    # the candidates from which the missing 30 mm and 5 mm fillets will be
    # selected by position and face adjacency in the next iteration.
    print("--- Global R02 edges near +Y side (y >= 289.9, x <= 100.1) ---")
    for i, edge in enumerate(shape.Edges()):
        ebb = edge.BoundingBox()
        if ebb.xmin <= 100.1 and ebb.ymax >= 289.9:
            c = edge.Center()
            try:
                gt = edge.geomType()
            except Exception:
                gt = "UNKNOWN"
            adjacent = []
            for k, face in enumerate(faces):
                if any(edge.isSame(face_edge) for face_edge in face.Edges()):
                    adjacent.append(k)
            print(
                f"EDGE {i}: type={gt}, length={edge.Length():.6f}, "
                f"center=({c.x:.6f},{c.y:.6f},{c.z:.6f}), "
                f"bbox=({ebb.xmin:.6f}..{ebb.xmax:.6f}, "
                f"{ebb.ymin:.6f}..{ebb.ymax:.6f}, "
                f"{ebb.zmin:.6f}..{ebb.zmax:.6f}), adjacent_faces={adjacent}"
            )

    print("=== END MODEL INSPECTION ===")
    return model