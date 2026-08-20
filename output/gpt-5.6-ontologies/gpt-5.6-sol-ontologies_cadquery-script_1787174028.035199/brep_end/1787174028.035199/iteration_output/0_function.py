def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root_shape = imported.val() if hasattr(imported, "val") else imported

    solids = root_shape.Solids()
    if len(solids) != 1:
        raise ValueError(f"Expected one solid (SOLID 0), found {len(solids)}")
    solid = solids[0]

    print(f"Input valid: {solid.isValid()}")
    print(f"Input volume: {solid.Volume():.6f} mm^3")
    print(f"Input faces: {len(solid.Faces())}")
    print(f"Input edges: {len(solid.Edges())}")

    for index, face in enumerate(solid.Faces()):
        center = face.Center()
        bbox = face.BoundingBox()
        try:
            geometry_type = face.geomType()
        except Exception:
            geometry_type = "Unknown"
        print(
            f"FACE {index}: type={geometry_type}, "
            f"center=({center.x:.6f}, {center.y:.6f}, {center.z:.6f}), "
            f"area={face.Area():.6f}, "
            f"bbox=({bbox.xmin:.6f},{bbox.ymin:.6f},{bbox.zmin:.6f})-"
            f"({bbox.xmax:.6f},{bbox.ymax:.6f},{bbox.zmax:.6f})"
        )

    original_edges = solid.Edges()
    for index, edge in enumerate(original_edges):
        center = edge.Center()
        try:
            geometry_type = edge.geomType()
        except Exception:
            geometry_type = "Unknown"
        print(
            f"EDGE {index}: type={geometry_type}, length={edge.Length():.6f}, "
            f"center=({center.x:.6f}, {center.y:.6f}, {center.z:.6f})"
        )

    radius = 0.2
    result = cq.Workplane(obj=solid).edges().fillet(radius)
    result_shape = result.val()

    if not result_shape.isValid():
        raise ValueError("The all-edge 0.2 mm fillet produced an invalid shape")

    print(f"Applied R={radius:.6f} mm fillets to all {len(original_edges)} original edges")
    print(f"Result valid: {result_shape.isValid()}")
    print(f"Result solids: {len(result_shape.Solids())}")
    print(f"Result faces: {len(result_shape.Faces())}")
    print(f"Result edges: {len(result_shape.Edges())}")
    print(f"Result volume: {result_shape.Volume():.6f} mm^3")
    return result