def my_cad_function(args):
    import os

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    source_shape = imported.val()
    source_solids = list(source_shape.Solids())

    if not source_solids:
        raise ValueError("The imported STEP model contains no solids.")

    target_index = max(range(len(source_solids)), key=lambda i: source_solids[i].Volume())
    target = source_solids[target_index]
    original_volume = target.Volume()

    rail_x_center = -88.9
    slot_length = 30.0
    slot_width = 7.0
    recess_depth = 3.2
    cutter_overrun = 0.8

    pattern_positions = [
        -195.0, -165.0, -135.0, -105.0, -75.0, -45.0,
          45.0,   75.0,  105.0,  135.0, 165.0, 195.0
    ]

    def capsule_cutter(y_start, y_depth, z_center):
        radius = slot_width / 2.0
        straight_length = slot_length - slot_width
        x1 = rail_x_center - straight_length / 2.0
        x2 = rail_x_center + straight_length / 2.0

        middle = cq.Solid.makeBox(
            straight_length,
            y_depth,
            slot_width,
            cq.Vector(x1, y_start, z_center - radius)
        )
        end1 = cq.Solid.makeCylinder(
            radius,
            y_depth,
            cq.Vector(x1, y_start, z_center),
            cq.Vector(0, 1, 0)
        )
        end2 = cq.Solid.makeCylinder(
            radius,
            y_depth,
            cq.Vector(x2, y_start, z_center),
            cq.Vector(0, 1, 0)
        )
        return middle.fuse(end1).fuse(end2)

    cutters = []

    top_surface_y = 174.852
    top_start_y = top_surface_y - recess_depth
    top_depth = recess_depth + cutter_overrun
    for z_pos in pattern_positions:
        cutters.append(capsule_cutter(top_start_y, top_depth, z_pos))

    bottom_surface_y = -171.450
    bottom_start_y = bottom_surface_y - cutter_overrun
    bottom_depth = recess_depth + cutter_overrun
    for z_pos in pattern_positions:
        cutters.append(capsule_cutter(bottom_start_y, bottom_depth, z_pos))

    try:
        modified_target = target.cut(*cutters)
    except Exception as batch_error:
        print("Batch Boolean cut failed; applying cutters sequentially:", batch_error)
        modified_target = target
        successful_cuts = 0
        for cutter in cutters:
            try:
                candidate = modified_target.cut(cutter)
                if candidate.Volume() < modified_target.Volume() - 1.0e-5:
                    modified_target = candidate
                    successful_cuts += 1
            except Exception as cut_error:
                print("Individual slot cut failed:", cut_error)
        print("Sequential successful slot cuts:", successful_cuts)

    removed_volume = original_volume - modified_target.Volume()
    print("Target solid index:", target_index)
    print("Requested top slots:", len(pattern_positions))
    print("Requested bottom slots:", len(pattern_positions))
    print("Original target volume: %.3f" % original_volume)
    print("Modified target volume: %.3f" % modified_target.Volume())
    print("Removed slot volume: %.3f" % removed_volume)

    if removed_volume <= 1.0e-4:
        raise RuntimeError("The slot cutters did not intersect the radiator rail solid.")

    result_shapes = []
    for i, solid in enumerate(source_solids):
        if i == target_index:
            modified_solids = list(modified_target.Solids())
            result_shapes.extend(modified_solids if modified_solids else [modified_target])
        else:
            result_shapes.append(solid)

    result = cq.Compound.makeCompound(result_shapes)
    print("Output solid count:", len(result.Solids()))
    print("Output bounding box:", result.BoundingBox())
    return cq.Workplane(obj=result)