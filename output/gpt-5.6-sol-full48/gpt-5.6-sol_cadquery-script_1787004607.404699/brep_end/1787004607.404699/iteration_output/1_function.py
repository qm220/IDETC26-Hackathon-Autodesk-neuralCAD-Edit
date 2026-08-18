def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported

    solids = list(root.Solids())
    if len(solids) < 2:
        raise ValueError("Expected the STEP model to contain the housing and a separate control wheel")

    solids.sort(key=lambda s: s.Volume(), reverse=True)
    housing = solids[0]
    other_solids = solids[1:]

    rim_edges = []
    for edge in housing.Edges():
        bb = edge.BoundingBox()
        dx = bb.xmax - bb.xmin
        dz = bb.zmax - bb.zmin
        in_slot_region = (
            bb.xmin >= 23.5 and bb.xmax <= 32.0 and
            bb.zmin >= 42.0 and bb.zmax <= 61.0
        )
        is_above_floor = bb.ymax > 11.0
        is_rim_direction = max(dx, dz) > 2.0
        if in_slot_region and is_above_floor and is_rim_direction:
            rim_edges.append(edge)

    if len(rim_edges) != 4:
        raise ValueError("Expected exactly four upper wheel-slot rim edges; found %d" % len(rim_edges))

    filleted_housing = housing.fillet(2.0, rim_edges)
    if not filleted_housing.isValid():
        raise ValueError("The housing became invalid after applying the slot-rim fillet")

    return cq.Compound.makeCompound([filleted_housing] + other_solids)