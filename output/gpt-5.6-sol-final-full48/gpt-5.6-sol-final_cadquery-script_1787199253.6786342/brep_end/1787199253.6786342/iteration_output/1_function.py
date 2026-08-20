def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    shape = imported.val()
    edges = shape.Edges()

    print(f"Input valid: {shape.isValid()}")
    print(f"Input solids: {len(shape.Solids())}")
    print(f"Input edges: {len(edges)}")

    # CadQuery exposes filleting through Solid.fillet() or Workplane.fillet().
    # Apply one constant-radius operation to every edge of the original solid.
    result_shape = shape.fillet(0.2, edges)

    print(f"Output valid: {result_shape.isValid()}")
    print(f"Output solids: {len(result_shape.Solids())}")
    print(f"Output edges: {len(result_shape.Edges())}")
    return cq.Workplane("XY").newObject([result_shape])