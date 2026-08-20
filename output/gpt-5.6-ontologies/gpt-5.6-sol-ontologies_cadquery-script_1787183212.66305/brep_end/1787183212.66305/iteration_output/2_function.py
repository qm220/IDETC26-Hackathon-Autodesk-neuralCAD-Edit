def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model
    solids = list(shape.Solids())

    if len(solids) < 2:
        raise ValueError("The imported model does not contain enough solids.")

    platform_indices = set(
        sorted(range(len(solids)), key=lambda i: solids[i].Volume(), reverse=True)[:2]
    )

    edited_solids = []
    total_holes = 0
    original_volume = shape.Volume()

    for index, solid in enumerate(solids):
        if index not in platform_indices:
            edited_solids.append(solid)
            continue

        bb = solid.BoundingBox()
        x_span = bb.xmax - bb.xmin
        y_span = bb.ymax - bb.ymin
        z_span = bb.zmax - bb.zmin
        z_center = 0.5 * (bb.zmin + bb.zmax)

        x_fractions = (0.38, 0.49, 0.60, 0.71, 0.82)
        row_offsets = (-0.28 * z_span, 0.0, 0.28 * z_span)
        hole_radius = min(3.0, 0.20 * y_span)

        edited_platform = solid
        for z_offset in row_offsets:
            z = z_center + z_offset
            for fraction in x_fractions:
                x = bb.xmin + fraction * x_span
                cutter = cq.Solid.makeCylinder(
                    hole_radius,
                    y_span + 2.0,
                    cq.Vector(x, bb.ymin - 1.0, z),
                    cq.Vector(0.0, 1.0, 0.0),
                )
                edited_platform = edited_platform.cut(cutter)
                total_holes += 1

        if not edited_platform.isValid():
            raise ValueError(f"Boolean hole operation made platform solid {index} invalid.")

        edited_solids.append(edited_platform)

    result_shape = cq.Compound.makeCompound(edited_solids)
    result = cq.Workplane("XY").newObject([result_shape])

    final_volume = result_shape.Volume()
    print(f"Loaded: {input_file}")
    print(f"Edited platform solid indices: {sorted(platform_indices)}")
    print("Hole layout: 3 linear patterns x 5 holes per platform")
    print(f"Added cylindrical through-holes: {total_holes}")
    print(f"Original volume: {original_volume:.6f}")
    print(f"Final volume: {final_volume:.6f}")
    print(f"Removed volume: {original_volume - final_volume:.6f}")
    print(f"Result valid: {result_shape.isValid()}")
    print(f"Result solids: {len(result_shape.Solids())}")

    return result