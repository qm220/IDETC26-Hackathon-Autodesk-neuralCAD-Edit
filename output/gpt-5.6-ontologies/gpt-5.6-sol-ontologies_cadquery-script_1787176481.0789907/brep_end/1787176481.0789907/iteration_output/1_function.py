def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    solids = list(shape.Solids())
    if len(solids) != 3:
        raise ValueError(f"Expected 3 solids in the imported model, found {len(solids)}")

    blade = solids[0]

    # The target is the unique uninterrupted sharp edge running along the
    # full length of the diagonal blade. Its measured length is 381 mm.
    candidates = [
        edge for edge in blade.Edges()
        if abs(edge.Length() - 381.0) < 0.05
    ]

    if len(candidates) != 1:
        details = [
            (edge.Length(), edge.Center().toTuple())
            for edge in blade.Edges()
            if edge.Length() > 300.0
        ]
        raise ValueError(
            f"Expected one full-length unrounded blade edge, found {len(candidates)}. "
            f"Long-edge candidates: {details}"
        )

    target_edge = candidates[0]
    radius_mm = 6.35  # 0.635 cm
    edited_blade = blade.makeFillet(radius_mm, [target_edge])

    if not edited_blade.isValid():
        raise ValueError("The blade became invalid after applying the requested fillet")

    result = cq.Compound.makeCompound([
        edited_blade,
        solids[1],
        solids[2]
    ])

    print(f"Applied R={radius_mm:.3f} mm to one blade edge")
    print(f"Target edge length before edit: {target_edge.Length():.3f} mm")
    print(f"Target edge center: {target_edge.Center().toTuple()}")
    print(f"Result valid: {result.isValid()}")
    print(f"Result solids: {len(result.Solids())}, faces: {len(result.Faces())}")

    return cq.Workplane("XY").newObject([result])