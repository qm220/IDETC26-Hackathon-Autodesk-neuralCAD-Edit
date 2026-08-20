def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    print(f"Model valid: {shape.isValid()}")
    print(f"Model type: {shape.ShapeType()}")
    print(f"Faces: {len(shape.Faces())}, edges: {len(shape.Edges())}, solids: {len(shape.Solids())}")
    bb = shape.BoundingBox()
    print(f"Bounding box: x=({bb.xmin:.3f},{bb.xmax:.3f}) y=({bb.ymin:.3f},{bb.ymax:.3f}) z=({bb.zmin:.3f},{bb.zmax:.3f})")

    for si, solid in enumerate(shape.Solids()):
        sb = solid.BoundingBox()
        sc = solid.Center()
        print(f"SOLID {si}: volume={solid.Volume():.3f}, center=({sc.x:.3f},{sc.y:.3f},{sc.z:.3f}), bbox=({sb.xlen:.3f},{sb.ylen:.3f},{sb.zlen:.3f}), faces={len(solid.Faces())}")

    faces = shape.Faces()
    for fi, face in enumerate(faces):
        c = face.Center()
        try:
            geom = face.geomType()
        except Exception:
            geom = "UNKNOWN"
        try:
            n = face.normalAt()
            normal_text = f"({n.x:.3f},{n.y:.3f},{n.z:.3f})"
        except Exception:
            normal_text = "n/a"
        edge_data = []
        for edge in face.Edges():
            ec = edge.Center()
            edge_data.append(f"{edge.Length():.3f}@({ec.x:.2f},{ec.y:.2f},{ec.z:.2f})")
        print(f"FACE {fi}: type={geom}, area={face.Area():.3f}, center=({c.x:.3f},{c.y:.3f},{c.z:.3f}), normal={normal_text}, edges=[{' ; '.join(edge_data)}]")

    print("Longest global edges:")
    indexed_edges = list(enumerate(shape.Edges()))
    indexed_edges.sort(key=lambda item: item[1].Length(), reverse=True)
    for ei, edge in indexed_edges[:40]:
        c = edge.Center()
        try:
            geom = edge.geomType()
        except Exception:
            geom = "UNKNOWN"
        adjacent = [fi for fi, face in enumerate(faces) if any(edge.isSame(fe) for fe in face.Edges())]
        print(f"EDGE {ei}: type={geom}, length={edge.Length():.3f}, center=({c.x:.3f},{c.y:.3f},{c.z:.3f}), adjacent_faces={adjacent}")

    return model