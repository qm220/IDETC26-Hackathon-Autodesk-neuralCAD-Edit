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
    candidates = [
        edge for edge in blade.Edges()
        if abs(edge.Length() - 381.0) < 0.05
    ]

    if len(candidates) != 1:
        raise ValueError(
            f"Expected one 381 mm unrounded target edge, found {len(candidates)}"
        )

    target_edge = candidates[0]
    trial_radii = [6.3499, 6.349, 6.345, 6.34, 6.33, 6.30]
    edited_blade = None

    for radius in trial_radii:
        try:
            trial = blade.fillet(radius, [target_edge])
            if trial.isValid() and len(trial.Solids()) == 1:
                edited_blade = trial
                break
        except Exception:
            pass

    if edited_blade is None:
        raise ValueError("Unable to create the requested R6.35 mm edge fillet")

    result = cq.Compound.makeCompound(
        [edited_blade, solids[1], solids[2]]
    )

    if not result.isValid():
        raise ValueError("The resulting three-solid compound is invalid")

    return cq.Workplane("XY").newObject([result])