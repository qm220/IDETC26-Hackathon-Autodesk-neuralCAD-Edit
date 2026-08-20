def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    solids = list(shape.Solids())
    if len(solids) != 3:
        raise ValueError(f"Expected 3 solids in the imported model, found {len(solids)}")

    blade = solids[0]

    # The blade has one unique uninterrupted sharp longitudinal edge whose
    # measured length in the source model is 381 mm.
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

    # CadQuery Solid exposes fillet(), not makeFillet().
    edited_blade = blade.fillet(radius_mm, [target_edge])

    if not edited_blade.isValid():
        raise ValueError("The blade became invalid after applying the requested fillet")

    output_solids = [edited_blade, solids[1], solids[2]]
    result = cq.Compound.makeCompound(output_solids)

    if not result.isValid():
        raise ValueError("The resulting three-solid compound is invalid")

    print(f"Applied R={radius_mm:.3f} mm to one blade edge")
    print(f"Target edge length before edit: {target_edge.Length():.3f} mm")
    print(f"Target edge center: {target_edge.Center().toTuple()}")
    print(f"Edited blade valid: {edited_blade.isValid()}")
    print(f"Result valid: {result.isValid()}")
    print(f"Result solids: {len(result.Solids())}, faces: {len(result.Faces())}")

    return cq.Workplane("XY").newObject([result])