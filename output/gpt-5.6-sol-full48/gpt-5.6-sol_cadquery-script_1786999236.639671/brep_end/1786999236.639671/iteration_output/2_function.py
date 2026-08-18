def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    target_edges = []
    for edge in shape.Edges():
        try:
            if edge.geomType() != "CIRCLE":
                continue
            if abs(edge.radius() - 0.75) > 1.0e-4:
                continue

            center = edge.Center()
            if 4.6 < center.x < 7.7 and 3.4 < center.y < 3.7 and 2.8 < center.z < 3.1:
                target_edges.append(edge)
        except Exception:
            pass

    print(f"Selected clevis bore rim edges: {len(target_edges)}")
    for i, edge in enumerate(target_edges):
        c = edge.Center()
        print(
            f"target[{i}] radius={edge.radius():.6f} "
            f"center=({c.x:.6f},{c.y:.6f},{c.z:.6f})"
        )

    if len(target_edges) != 4:
        raise RuntimeError(
            f"Expected exactly four clevis pin-bore rim edges, found {len(target_edges)}"
        )

    result = cq.Workplane(obj=shape).newObject(target_edges).chamfer(0.2)
    result_shape = result.val()

    print(f"Result valid: {result_shape.isValid()}")
    print(
        f"Result solids: {len(result_shape.Solids())}, "
        f"faces: {len(result_shape.Faces())}, edges: {len(result_shape.Edges())}"
    )

    if not result_shape.isValid() or len(result_shape.Solids()) != 1:
        raise RuntimeError("Chamfer operation did not produce one valid solid")

    return result