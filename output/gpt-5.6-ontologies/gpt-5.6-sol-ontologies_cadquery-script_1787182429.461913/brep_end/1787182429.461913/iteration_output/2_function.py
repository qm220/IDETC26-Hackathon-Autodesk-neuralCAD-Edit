def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    root = model.val() if hasattr(model, "val") else model
    solids = list(root.Solids())

    if len(solids) != 9:
        raise ValueError(f"Expected 9 solids in the imported model, found {len(solids)}")

    heatbreak = solids[3]
    target_edges = []

    for edge in heatbreak.Edges():
        if edge.geomType() != "CIRCLE":
            continue
        try:
            radius = edge.radius()
            center = edge.Center()
        except Exception:
            continue

        if (
            abs(radius - 3.45) < 1.0e-4
            and abs(center.x) < 1.0e-4
            and abs(center.y + 40.0) < 1.0e-4
            and abs(center.z - 7.5) < 1.0e-4
        ):
            target_edges.append(edge)

    if len(target_edges) != 1:
        raise ValueError(
            "Could not uniquely identify the lower circular edge of the "
            "Heatbreak's main cylindrical section"
        )

    edited_heatbreak = (
        cq.Workplane(obj=heatbreak)
        .newObject(target_edges)
        .chamfer(0.2)
        .val()
    )

    if not edited_heatbreak.isValid():
        raise ValueError("The chamfered Heatbreak solid is invalid")

    output_solids = list(solids)
    output_solids[3] = edited_heatbreak
    result = cq.Compound.makeCompound(output_solids)

    if not result.isValid() or len(result.Solids()) != 9:
        raise ValueError("The edited nine-component model is invalid")

    return cq.Workplane(obj=result)