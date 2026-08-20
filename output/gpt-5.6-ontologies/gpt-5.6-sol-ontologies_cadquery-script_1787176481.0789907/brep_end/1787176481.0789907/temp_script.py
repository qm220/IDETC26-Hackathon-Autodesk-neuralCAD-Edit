def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()
    solids = list(shape.Solids())

    if len(solids) != 3:
        raise ValueError(f"Expected 3 solids, found {len(solids)}")

    blade = solids[0]

    # The source blade contains one uninterrupted sharp longitudinal edge
    # measuring 381 mm. This distinguishes it from the already-rounded side.
    candidates = [
        edge for edge in blade.Edges()
        if abs(edge.Length() - 381.0) < 0.05
    ]

    if len(candidates) != 1:
        long_edges = sorted(
            [(e.Length(), e.Center().toTuple()) for e in blade.Edges()
             if e.Length() > 300.0],
            reverse=True
        )
        raise ValueError(
            f"Expected one 381 mm target edge, found {len(candidates)}. "
            f"Long edges: {long_edges}"
        )

    target_edge = candidates[0]
    requested_radius = 6.35

    # R6.35 is nominally half the relevant blade thickness. OCC can reject
    # a fillet at the exact limiting radius because the residual face becomes
    # degenerate. Start essentially at nominal and reduce only by tiny modeling
    # tolerances until the valid limiting fillet is found.
    trial_radii = [6.3499, 6.349, 6.345, 6.34, 6.33, 6.30]
    edited_blade = None
    used_radius = None
    failures = []

    for radius in trial_radii:
        try:
            trial = blade.fillet(radius, [target_edge])
            if trial.isValid() and len(trial.Solids()) == 1:
                edited_blade = trial
                used_radius = radius
                break
            failures.append(f"R={radius}: invalid result")
        except Exception as exc:
            failures.append(f"R={radius}: {type(exc).__name__}: {exc}")

    if edited_blade is None:
        raise ValueError(
            "Unable to create the requested limiting-radius fillet. "
            + " | ".join(failures)
        )

    result = cq.Compound.makeCompound(
        [edited_blade, solids[1], solids[2]]
    )

    if not result.isValid():
        raise ValueError("The resulting three-solid compound is invalid")

    print(f"Target edge length: {target_edge.Length():.6f} mm")
    print(f"Target edge center: {target_edge.Center().toTuple()}")
    print(f"Requested radius: {requested_radius:.6f} mm")
    print(f"Applied radius: {used_radius:.6f} mm")
    print(f"Nominal deviation: {requested_radius - used_radius:.6f} mm")
    print(f"Result solids: {len(result.Solids())}")
    print(f"Result valid: {result.isValid()}")
    if failures:
        print("Earlier trial results: " + " | ".join(failures))

    return cq.Workplane("XY").newObject([result])