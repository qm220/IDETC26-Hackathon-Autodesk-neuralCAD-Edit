def my_cad_function(args):
    import os
    import cadquery as cq
    from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    # The enlarged end occupies x <= 100. Its lower perimeter already has
    # 30 mm primary rounds and 5 mm rounds near the shank-side shoulder.
    # Apply matching radii to the corresponding sharp upper perimeter edges.
    large_radius_edges = []
    small_radius_edges = []
    tol = 1.0e-3

    for edge in shape.Edges():
        bb = edge.BoundingBox()

        # Sharp perimeter edges lying in the upper face of the enlarged body.
        on_upper_face = (
            abs(bb.zmin - (-340.0)) < tol and
            abs(bb.zmax - (-340.0)) < tol
        )
        in_enlarged_body = bb.xmax <= 100.0 + tol

        if not (on_upper_face and in_enlarged_body):
            continue

        # These three edges correspond to the existing 5 mm underside rounds:
        # the x=100 shoulder edge, its plan-view corner, and the y=320 edge.
        is_small_radius_region = (
            bb.xmin >= 100.0 - tol or
            bb.ymin >= 315.0 - tol
        )

        if is_small_radius_region:
            small_radius_edges.append(edge)
        else:
            # Remaining enlarged-body upper perimeter edges correspond to the
            # existing 30 mm lower-side rounds.
            large_radius_edges.append(edge)

    print("Selected upper enlarged-body edges:",
          "R30 =", len(large_radius_edges),
          "R5 =", len(small_radius_edges))

    if len(large_radius_edges) != 5 or len(small_radius_edges) != 3:
        raise ValueError(
            "Unexpected enlarged-body edge selection; refusing to modify unrelated geometry"
        )

    # Build both radius groups together so OpenCascade creates the proper
    # mixed-radius corner transition where the 30 mm and 5 mm rounds meet.
    fillet_builder = BRepFilletAPI_MakeFillet(shape.wrapped)
    for edge in large_radius_edges:
        fillet_builder.Add(30.0, edge.wrapped)
    for edge in small_radius_edges:
        fillet_builder.Add(5.0, edge.wrapped)

    fillet_builder.Build()
    if not fillet_builder.IsDone():
        raise RuntimeError("OpenCascade could not construct the matching upper fillets")

    result_shape = cq.Shape.cast(fillet_builder.Shape())
    result = cq.Workplane(obj=result_shape)

    bbox = result_shape.BoundingBox()
    print("VALID", result_shape.isValid())
    print("VOLUME", result_shape.Volume())
    print("BBOX", bbox.xmin, bbox.xmax, bbox.ymin, bbox.ymax, bbox.zmin, bbox.zmax)
    print("COUNTS faces edges vertices",
          len(result_shape.Faces()),
          len(result_shape.Edges()),
          len(result_shape.Vertices()))

    if not result_shape.isValid():
        raise RuntimeError("Filleted result is not a valid solid")

    return result