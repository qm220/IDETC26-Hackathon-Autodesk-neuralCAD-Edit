def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()
    solids = list(shape.Solids())

    if not solids:
        raise ValueError("No solids were found in the imported STEP model.")

    # S12 is the tall, coaxial operating lever. Its free end is the highest
    # planar end in the assembly. Select the narrow solid having the greatest
    # Z maximum rather than relying on STEP solid ordering.
    candidates = []
    for i, solid in enumerate(solids):
        bb = solid.BoundingBox()
        if bb.xlen < 45.0 and bb.ylen < 45.0 and bb.zlen > 80.0:
            candidates.append((bb.zmax, i, solid, bb))

    if not candidates:
        raise ValueError("Could not identify the tall operating-lever solid.")

    _, lever_index, lever, lever_bb = max(candidates, key=lambda item: item[0])

    center_x = 0.5 * (lever_bb.xmin + lever_bb.xmax)
    center_y = 0.5 * (lever_bb.ymin + lever_bb.ymax)
    grip_radius = 0.25 * (lever_bb.xlen + lever_bb.ylen)
    extension_distance = 50.0
    overlap = 0.10

    # Continue the existing cylindrical grip from its free cap along its
    # longitudinal axis. A slight overlap ensures a reliable additive union,
    # while the final endpoint remains exactly 50 mm beyond the original cap.
    extension = cq.Solid.makeCylinder(
        grip_radius,
        extension_distance + overlap,
        cq.Vector(center_x, center_y, lever_bb.zmax - overlap),
        cq.Vector(0, 0, 1)
    )

    extended_lever = lever.fuse(extension)
    if not extended_lever.isValid():
        raise ValueError("The extended operating lever is not a valid solid.")

    result_solids = [extended_lever if i == lever_index else solid
                     for i, solid in enumerate(solids)]
    result = cq.Compound.makeCompound(result_solids)

    new_bb = extended_lever.BoundingBox()
    print(f"Operating lever solid index: {lever_index}")
    print(f"Original lever Z range: {lever_bb.zmin:.3f} to {lever_bb.zmax:.3f} mm")
    print(f"Extended lever Z range: {new_bb.zmin:.3f} to {new_bb.zmax:.3f} mm")
    print(f"Applied free-end extension: {new_bb.zmax - lever_bb.zmax:.3f} mm")
    print(f"Preserved grip diameter: {2.0 * grip_radius:.3f} mm")
    print(f"Result valid: {result.isValid()}")

    return cq.Workplane("XY").newObject([result])