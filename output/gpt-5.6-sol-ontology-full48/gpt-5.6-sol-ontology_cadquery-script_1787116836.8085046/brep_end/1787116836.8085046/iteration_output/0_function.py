def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported

    solids = root.Solids()
    faces = root.Faces()
    edges = root.Edges()
    print("MODEL INSPECTION")
    print(f"Valid: {root.isValid()}")
    print(f"Solids: {len(solids)}, Faces: {len(faces)}, Edges: {len(edges)}")

    for si, solid in enumerate(solids):
        bb = solid.BoundingBox()
        c = solid.Center()
        print(
            f"SOLID {si}: valid={solid.isValid()} volume={solid.Volume():.6f} "
            f"faces={len(solid.Faces())} center=({c.x:.6f},{c.y:.6f},{c.z:.6f}) "
            f"bbox=({bb.xmin:.6f},{bb.ymin:.6f},{bb.zmin:.6f})-"
            f"({bb.xmax:.6f},{bb.ymax:.6f},{bb.zmax:.6f})"
        )

    for i, face in enumerate(faces):
        c = face.Center()
        bb = face.BoundingBox()
        try:
            gt = face.geomType()
        except Exception:
            gt = "UNKNOWN"
        try:
            n = face.normalAt(c)
            normal_text = f"({n.x:.5f},{n.y:.5f},{n.z:.5f})"
        except Exception:
            normal_text = "unavailable"
        print(
            f"FACE {i}: type={gt} area={face.Area():.6f} "
            f"center=({c.x:.6f},{c.y:.6f},{c.z:.6f}) normal={normal_text} "
            f"wires={len(face.Wires())} edges={len(face.Edges())} "
            f"bbox=({bb.xmin:.6f},{bb.ymin:.6f},{bb.zmin:.6f})-"
            f"({bb.xmax:.6f},{bb.ymax:.6f},{bb.zmax:.6f})"
        )

    # Inspect the planned upper housing face and bind every wire edge to the
    # actual global STEP edge and its adjacent faces.
    if len(faces) > 6:
        target_face = faces[6]
        print("FACE 6 WIRE TOPOLOGY")
        for wi, wire in enumerate(target_face.Wires()):
            print(f"  WIRE {wi}: length={wire.Length():.6f} edges={len(wire.Edges())}")
            for local_i, edge in enumerate(wire.Edges()):
                ec = edge.Center()
                ebb = edge.BoundingBox()
                global_ids = [j for j, candidate in enumerate(edges) if edge.isSame(candidate)]
                adjacent = []
                for fj, candidate_face in enumerate(faces):
                    if any(edge.isSame(fe) for fe in candidate_face.Edges()):
                        adjacent.append(fj)
                try:
                    curve_type = edge.geomType()
                except Exception:
                    curve_type = "UNKNOWN"
                print(
                    f"    edge local={local_i} global={global_ids} type={curve_type} "
                    f"length={edge.Length():.6f} center=({ec.x:.6f},{ec.y:.6f},{ec.z:.6f}) "
                    f"adjacent_faces={adjacent} "
                    f"bbox=({ebb.xmin:.6f},{ebb.ymin:.6f},{ebb.zmin:.6f})-"
                    f"({ebb.xmax:.6f},{ebb.ymax:.6f},{ebb.zmax:.6f})"
                )

    # Also report edges shared directly between FACE 6 and the grounded
    # pedestal faces FACE 0 through FACE 3.
    if len(faces) > 6:
        for pedestal_face_id in range(4):
            shared = []
            for edge in faces[6].Edges():
                if any(edge.isSame(other) for other in faces[pedestal_face_id].Edges()):
                    shared.extend(j for j, candidate in enumerate(edges) if edge.isSame(candidate))
            print(f"Shared global edges FACE 6 / FACE {pedestal_face_id}: {sorted(set(shared))}")

    # This first pass intentionally returns the inspected source unchanged;
    # the diagnostics bind planning face numbers to the imported topology.
    return imported