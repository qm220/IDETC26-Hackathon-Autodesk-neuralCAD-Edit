def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    shape = imported.val() if hasattr(imported, "val") else imported
    solids = list(shape.Solids())

    # Identified from the source B-rep:
    #   SOLID 12 = Cordholder / cord-guide bracket
    #   SOLID 17 = existing U-shaped external handle
    cordholder_index = 12
    handle_index = 17

    if len(solids) <= handle_index:
        raise ValueError("Expected at least 18 solids in the input model")

    existing_handle = solids[handle_index]
    handle_bb = existing_handle.BoundingBox()

    # Trim the curved bottom of the handle with a horizontal plane. The retained
    # chord creates a broad, planar support region. It is slightly below the
    # existing mounting feet so the two handles serve as the primary stands.
    support_z = -145.0
    trim_volume = cq.Solid.makeBox(
        1000.0,
        1000.0,
        1000.0,
        cq.Vector(-500.0, -300.0, support_z)
    )
    trimmed_handle = existing_handle.intersect(trim_volume)

    # The enclosure extends from Y=0 to Y=355.6. Mirror the handle placement
    # about the enclosure's longitudinal midpoint so the added stand has the
    # same offset from the opposite end wall.
    enclosure_ymin = solids[0].BoundingBox().ymin
    enclosure_ymax = solids[0].BoundingBox().ymax
    enclosure_y_mid = 0.5 * (enclosure_ymin + enclosure_ymax)
    existing_handle_y_mid = 0.5 * (handle_bb.ymin + handle_bb.ymax)
    opposite_handle_y_mid = 2.0 * enclosure_y_mid - existing_handle_y_mid
    y_shift = opposite_handle_y_mid - existing_handle_y_mid
    added_handle = trimmed_handle.translate(cq.Vector(0.0, y_shift, 0.0))

    # Preserve every non-targeted solid, remove the Cordholder and replace the
    # original handle with its flat-bottom version plus one opposing copy.
    output_solids = []
    for i, solid in enumerate(solids):
        if i in (cordholder_index, handle_index):
            continue
        output_solids.append(solid)
    output_solids.extend([trimmed_handle, added_handle])

    result = cq.Compound.makeCompound(output_solids)

    print("Removed Cordholder solid:", cordholder_index)
    print("Existing handle original Y bounds:", handle_bb.ymin, handle_bb.ymax)
    print("Added handle Y shift:", y_shift)
    print("Flat support elevation for both handles:", support_z)
    print("Output solids:", len(result.Solids()), "valid:", result.isValid())

    return cq.Workplane("XY").newObject([result])