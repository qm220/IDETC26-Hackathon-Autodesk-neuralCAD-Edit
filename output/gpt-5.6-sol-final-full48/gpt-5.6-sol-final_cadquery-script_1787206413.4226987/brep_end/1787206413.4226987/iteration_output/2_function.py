def my_cad_function(args):
    import os

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    solids = list(imported.solids().vals())

    if len(solids) < 20:
        raise ValueError("Expected the 20-solid source assembly")

    handle_index = 7
    pot_indices = (8, 9)
    support_index = 6

    handle = solids[handle_index]
    pots = [solids[i] for i in pot_indices]
    support = solids[support_index]

    handle_bb = handle.BoundingBox()
    outer_pot_bb = solids[8].BoundingBox()
    support_bb = support.BoundingBox()

    initial_pot_gap = handle_bb.ymin - outer_pot_bb.ymax
    desired_clearance = 5.0
    requested_shift = max(0.0, desired_clearance - initial_pot_gap)

    initial_support_gap = support_bb.ymin - handle_bb.ymax
    minimum_support_clearance = 0.25
    maximum_safe_shift = max(0.0, initial_support_gap - minimum_support_clearance)
    shift_y = min(requested_shift, maximum_safe_shift)

    edited_handle = handle.translate((0.0, shift_y, 0.0)) if shift_y > 1.0e-7 else handle

    handle_pot_interference = sum(edited_handle.intersect(pot).Volume() for pot in pots)
    handle_support_interference = edited_handle.intersect(support).Volume()

    if handle_pot_interference > 1.0e-6:
        raise ValueError("Handle still interferes with the coffee pot")
    if handle_support_interference > 1.0e-6:
        raise ValueError("Handle relocation interferes with the support plate")
    if abs(edited_handle.Volume() - handle.Volume()) > max(1.0e-5, handle.Volume() * 1.0e-8):
        raise ValueError("Unexpected handle volume change")

    output_shapes = [edited_handle if i == handle_index else solid for i, solid in enumerate(solids)]
    return cq.Compound.makeCompound(output_shapes)