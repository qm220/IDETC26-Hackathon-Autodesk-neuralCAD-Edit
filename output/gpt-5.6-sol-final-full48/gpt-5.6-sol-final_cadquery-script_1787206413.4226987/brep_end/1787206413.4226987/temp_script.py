def my_cad_function(args):
    import os

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    solids = list(imported.solids().vals())
    print(f"Imported {len(solids)} solids")

    if len(solids) < 20:
        raise ValueError("Expected the 20-solid source assembly")

    # Model-semantic assignments:
    # 7: front pull handle
    # 8: outer coffee-pot vessel
    # 9: inner coffee-pot liner
    # 6: adjacent front support plate, which must not be contacted by the move
    handle_index = 7
    pot_indices = (8, 9)
    support_index = 6

    handle = solids[handle_index]
    pots = [solids[i] for i in pot_indices]
    support = solids[support_index]

    hb = handle.BoundingBox()
    outer_pot_bb = solids[8].BoundingBox()
    support_bb = support.BoundingBox()

    initial_pot_gap = hb.ymin - outer_pot_bb.ymax
    initial_support_gap = support_bb.ymin - hb.ymax
    print(f"Initial handle-to-pot axial gap: {initial_pot_gap:.6f} mm")
    print(f"Initial handle-to-support axial gap: {initial_support_gap:.6f} mm")

    initial_interference = 0.0
    for pot in pots:
        initial_interference += handle.intersect(pot).Volume()
    print(f"Initial handle/pot common volume: {initial_interference:.9f} mm^3")

    # The imported handle has no positive-volume Boolean overlap, but it lies in
    # the narrow space immediately in front of the pot. Move it only far enough
    # in the outward/front direction (+Y) to establish an explicit practical
    # 5 mm handle-to-pot clearance. This preserves the complete grip B-rep and
    # avoids the destructive trimming attempted previously.
    desired_clearance = 5.0
    requested_shift = max(0.0, desired_clearance - initial_pot_gap)

    # Preserve a small nonzero clearance from the unchanged front support plate.
    minimum_support_clearance = 0.25
    maximum_safe_shift = max(0.0, initial_support_gap - minimum_support_clearance)
    shift_y = min(requested_shift, maximum_safe_shift)

    if shift_y <= 1.0e-7:
        print("No handle translation required or no safe translation available")
        edited_handle = handle
    else:
        edited_handle = handle.translate((0.0, shift_y, 0.0))
        print(f"Translated front pull handle outward by {shift_y:.6f} mm in +Y")

    final_interference = 0.0
    for pot in pots:
        final_interference += edited_handle.intersect(pot).Volume()
    support_interference = edited_handle.intersect(support).Volume()

    eb = edited_handle.BoundingBox()
    final_pot_gap = eb.ymin - outer_pot_bb.ymax
    final_support_gap = support_bb.ymin - eb.ymax

    print(f"Final handle-to-pot axial gap: {final_pot_gap:.6f} mm")
    print(f"Final handle-to-support axial gap: {final_support_gap:.6f} mm")
    print(f"Final handle/pot common volume: {final_interference:.9f} mm^3")
    print(f"Final handle/support common volume: {support_interference:.9f} mm^3")
    print(f"Handle volume before/after: {handle.Volume():.6f} / {edited_handle.Volume():.6f} mm^3")

    if final_interference > 1.0e-6:
        raise ValueError("Handle still has positive-volume interference with the coffee pot")
    if support_interference > 1.0e-6:
        raise ValueError("Handle relocation introduced interference with the support plate")
    if abs(edited_handle.Volume() - handle.Volume()) > max(1.0e-5, handle.Volume() * 1.0e-8):
        raise ValueError("Unexpected handle volume change during rigid relocation")

    # Replace only the front pull handle. All pot components, enclosure parts,
    # cradle, feet, cable, plug, and internal components retain their original
    # B-reps and assembly positions.
    output_shapes = []
    for i, solid in enumerate(solids):
        output_shapes.append(edited_handle if i == handle_index else solid)

    result = cq.Compound.makeCompound(output_shapes)
    print(f"Output contains {len(result.Solids())} solids")
    return result