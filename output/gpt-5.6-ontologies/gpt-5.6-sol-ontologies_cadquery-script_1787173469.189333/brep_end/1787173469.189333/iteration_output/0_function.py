def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported

    solids = list(root.Solids())
    faces = list(root.Faces())
    print(f"Loaded STEP: valid={root.isValid()}, solids={len(solids)}, faces={len(faces)}")

    for si, solid in enumerate(solids):
        bb = solid.BoundingBox()
        c = solid.Center()
        print(f"SOLID {si}: faces={len(solid.Faces())}, volume={solid.Volume():.6f}, center=({c.x:.4f},{c.y:.4f},{c.z:.4f}), bbox=({bb.xmin:.4f},{bb.ymin:.4f},{bb.zmin:.4f})-({bb.xmax:.4f},{bb.ymax:.4f},{bb.zmax:.4f})")

    for i, face in enumerate(faces):
        c = face.Center()
        try:
            gtype = face.geomType()
        except Exception:
            gtype = "unknown"
        print(f"FACE {i}: type={gtype}, area={face.Area():.6f}, center=({c.x:.4f},{c.y:.4f},{c.z:.4f}), edges={len(face.Edges())}")

    if len(solids) < 2 or len(faces) < 15:
        raise ValueError("The imported topology does not match the planned two-solid, fifteen-face model")

    housing = solids[0]
    wheel = solids[1]
    pocket_faces = faces[0:5]
    housing_outer_faces = faces[5:11]

    def edge_occurs_on(edge, face_group):
        return any(edge.isSame(face_edge) for face in face_group for face_edge in face.Edges())

    target_edges = []
    for edge in housing.Edges():
        if edge_occurs_on(edge, pocket_faces) and edge_occurs_on(edge, housing_outer_faces):
            target_edges.append(edge)

    print(f"Derived {len(target_edges)} slot-opening boundary edges")
    for i, edge in enumerate(target_edges):
        c = edge.Center()
        p0 = edge.startPoint()
        p1 = edge.endPoint()
        try:
            gtype = edge.geomType()
        except Exception:
            gtype = "unknown"
        print(f"TARGET EDGE {i}: type={gtype}, length={edge.Length():.6f}, center=({c.x:.4f},{c.y:.4f},{c.z:.4f}), start=({p0.x:.4f},{p0.y:.4f},{p0.z:.4f}), end=({p1.x:.4f},{p1.y:.4f},{p1.z:.4f})")

    if not target_edges:
        raise ValueError("No edges shared by the grounded pocket and outer-housing faces were found")

    filleted_wp = cq.Workplane(obj=housing).newObject(target_edges).fillet(2.0)
    filleted_housing = filleted_wp.val()
    print(f"Filleted housing: valid={filleted_housing.isValid()}, faces={len(filleted_housing.Faces())}, volume={filleted_housing.Volume():.6f}")

    result = cq.Compound.makeCompound([filleted_housing, wheel])
    print(f"Final result: valid={result.isValid()}, solids={len(result.Solids())}, faces={len(result.Faces())}")
    return cq.Workplane(obj=result)