def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    shape = imported.val() if hasattr(imported, "val") else imported
    solids = list(shape.Solids())

    cordholder_index = 12
    handle_index = 17

    if len(solids) <= handle_index:
        raise ValueError("Expected at least 18 solids in the input model")

    existing_handle = solids[handle_index]
    handle_bb = existing_handle.BoundingBox()

    support_z = -145.0
    trim_volume = cq.Solid.makeBox(
        1000.0,
        1000.0,
        1000.0,
        cq.Vector(-500.0, -300.0, support_z)
    )
    trimmed_handle = existing_handle.intersect(trim_volume)

    enclosure_ymin = solids[0].BoundingBox().ymin
    enclosure_ymax = solids[0].BoundingBox().ymax
    enclosure_y_mid = 0.5 * (enclosure_ymin + enclosure_ymax)
    existing_handle_y_mid = 0.5 * (handle_bb.ymin + handle_bb.ymax)
    opposite_handle_y_mid = 2.0 * enclosure_y_mid - existing_handle_y_mid
    y_shift = opposite_handle_y_mid - existing_handle_y_mid
    added_handle = trimmed_handle.translate(cq.Vector(0.0, y_shift, 0.0))

    output_solids = []
    for i, solid in enumerate(solids):
        if i in (cordholder_index, handle_index):
            continue
        output_solids.append(solid)
    output_solids.extend([trimmed_handle, added_handle])

    result = cq.Compound.makeCompound(output_solids)
    return cq.Workplane("XY").newObject([result])