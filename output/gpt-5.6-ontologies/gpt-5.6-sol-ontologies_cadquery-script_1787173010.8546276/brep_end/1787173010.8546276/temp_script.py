def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    shape = imported.val() if hasattr(imported, "val") else imported
    solids = list(shape.Solids())

    if not solids:
        raise ValueError("The imported STEP model contains no solids.")

    # SOLID 0 is the main radiator frame and plastic fan-support body. The
    # remaining solids are preserved without modification.
    plastic_body = solids[0]
    original_volume = plastic_body.Volume()

    # Add shallow capsule-shaped recessed slots to the opposing exterior
    # +Y (top) and -Y (bottom) rail surfaces. Two staggered columns distribute
    # the pattern across the available X-Z surface while avoiding the end caps.
    slot_length = 30.0
    slot_width = 6.0
    recess_depth = 4.0
    x_columns = (-100.0, -78.0)
    z_rows = (-216.0, -162.0, -108.0, -54.0, 0.0, 54.0, 108.0, 162.0, 216.0)

    top_start_y = 176.0
    bottom_start_y = -173.0
    slot_count = 0

    for row_index, z_base in enumerate(z_rows):
        for column_index, x_pos in enumerate(x_columns):
            # Slight staggering makes the repeated layout visually distinct
            # while retaining equal spacing across both side surfaces.
            z_pos = z_base + (7.0 if (column_index == 1 and row_index % 2 == 0) else 0.0)

            # XZ workplanes have a -Y normal. Positive extrusion therefore
            # cuts inward from the +Y/top surface.
            top_tool = (
                cq.Workplane("XZ", origin=(0.0, top_start_y, 0.0))
                .center(x_pos, z_pos)
                .slot2D(slot_length, slot_width, angle=90.0)
                .extrude(recess_depth + 1.0)
                .val()
            )
            plastic_body = plastic_body.cut(top_tool)

            # Negative extrusion from below proceeds in +Y, cutting inward
            # from the -Y/bottom surface.
            bottom_tool = (
                cq.Workplane("XZ", origin=(0.0, bottom_start_y, 0.0))
                .center(x_pos, z_pos)
                .slot2D(slot_length, slot_width, angle=90.0)
                .extrude(-(recess_depth + 1.0))
                .val()
            )
            plastic_body = plastic_body.cut(bottom_tool)
            slot_count += 2

    try:
        plastic_body = plastic_body.clean()
    except Exception:
        pass

    output_solids = list(plastic_body.Solids()) + solids[1:]
    result = cq.Compound.makeCompound(output_solids)

    print(f"Created {slot_count} recessed slots: {slot_count // 2} on +Y/top and {slot_count // 2} on -Y/bottom.")
    print(f"Plastic body volume: {original_volume:.3f} -> {plastic_body.Volume():.3f}")
    print(f"Output solid count: {len(result.Solids())}")
    print(f"Output bbox: {result.BoundingBox()}")

    return cq.Workplane("XY").newObject([result])