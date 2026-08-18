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

    print("Imported solids:", len(solids))
    for i, solid in enumerate(solids):
        bb = solid.BoundingBox()
        print(
            "Solid", i,
            "volume", round(solid.Volume(), 4),
            "bbox", (round(bb.xmin, 3), round(bb.ymin, 3), round(bb.zmin, 3)),
            "to", (round(bb.xmax, 3), round(bb.ymax, 3), round(bb.zmax, 3))
        )

    # The wheel-slot rim lies inside this compact transverse/longitudinal region.
    # Reject the floor edges at y=10 and the vertical pocket-corner edges by
    # requiring an appreciable span in x or z.
    rim_edges = []
    for edge in housing.Edges():
        bb = edge.BoundingBox()
        dx = bb.xmax - bb.xmin
        dy = bb.ymax - bb.ymin
        dz = bb.zmax - bb.zmin
        in_slot_region = (
            bb.xmin >= 23.5 and bb.xmax <= 32.0 and
            bb.zmin >= 42.0 and bb.zmax <= 61.0
        )
        is_above_floor = bb.ymax > 11.0
        is_rim_direction = max(dx, dz) > 2.0
        if in_slot_region and is_above_floor and is_rim_direction:
            rim_edges.append(edge)
            c = edge.Center()
            print(
                "Rim candidate:",
                "center", (round(c.x, 3), round(c.y, 3), round(c.z, 3)),
                "span", (round(dx, 3), round(dy, 3), round(dz, 3)),
                "length", round(edge.Length(), 3)
            )

    if len(rim_edges) != 4:
        raise ValueError("Expected exactly four upper wheel-slot rim edges; found %d" % len(rim_edges))

    filleted_housing = housing.fillet(2.0, rim_edges)
    if not filleted_housing.isValid():
        raise ValueError("The housing became invalid after applying the slot-rim fillet")

    print("Applied a 2 mm fillet to all four wheel-slot rim edges")
    print("Housing faces before/after:", len(housing.Faces()), len(filleted_housing.Faces()))
    print("Result valid:", filleted_housing.isValid())

    result_solids = [filleted_housing] + other_solids
    return cq.Compound.makeCompound(result_solids)
