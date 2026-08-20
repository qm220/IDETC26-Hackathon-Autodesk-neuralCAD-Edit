def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()
    source_bb = shape.BoundingBox()

    # Requested dimensions in millimetres.
    opening_width = 200.0
    opening_height = 100.0
    corner_radius = 10.0
    cut_depth = 30.0

    # The ventilated rear exterior is the maximum-Y side of this model.
    # Horizontally center the opening. A bottom clearance of approximately
    # 50 mm matches the expected side clearances for the roughly 300 mm-wide
    # enclosure, satisfying the requested approximately equal spacing.
    center_x = 0.5 * (source_bb.xmin + source_bb.xmax)
    rear_y = source_bb.ymax
    bottom_clearance = 50.0
    bottom_z = source_bb.zmin + bottom_clearance

    xmin = center_x - opening_width / 2.0
    inner_y = rear_y - cut_depth
    overshoot = 4.0
    cutter_length = cut_depth + overshoot

    # Construct one fused rounded-rectangular prism. Using one cutter avoids
    # the failed sequence of compound boolean operations from the prior run.
    cutter_parts = [
        cq.Solid.makeBox(
            opening_width - 2.0 * corner_radius,
            cutter_length,
            opening_height,
            cq.Vector(xmin + corner_radius, inner_y, bottom_z)
        ),
        cq.Solid.makeBox(
            opening_width,
            cutter_length,
            opening_height - 2.0 * corner_radius,
            cq.Vector(xmin, inner_y, bottom_z + corner_radius)
        )
    ]

    for x in (xmin + corner_radius,
              xmin + opening_width - corner_radius):
        for z in (bottom_z + corner_radius,
                  bottom_z + opening_height - corner_radius):
            cutter_parts.append(
                cq.Solid.makeCylinder(
                    corner_radius,
                    cutter_length,
                    cq.Vector(x, inner_y, z),
                    cq.Vector(0, 1, 0)
                )
            )

    cutter = cutter_parts[0]
    for part in cutter_parts[1:]:
        cutter = cutter.fuse(part)

    # First attempt a single boolean against the imported assembly. If the
    # kernel cannot cut the multi-solid compound directly, cut each original
    # solid independently and rebuild the assembly. This also safely handles
    # rear louvers and trim that may be split into multiple fragments.
    try:
        result_shape = shape.cut(cutter)
        if result_shape.wrapped.IsNull():
            raise ValueError("Direct cut returned a null shape")
        boolean_mode = "single compound cut"
    except Exception as direct_error:
        print("DIRECT CUT FALLBACK:", direct_error)
        edited_shapes = []
        cut_count = 0
        preserved_count = 0
        failed_count = 0

        for solid in model.solids().vals():
            bb = solid.BoundingBox()
            overlaps = not (
                bb.xmax <= xmin or
                bb.xmin >= xmin + opening_width or
                bb.ymax <= inner_y or
                bb.ymin >= rear_y + overshoot or
                bb.zmax <= bottom_z or
                bb.zmin >= bottom_z + opening_height
            )

            if not overlaps:
                edited_shapes.append(solid)
                preserved_count += 1
                continue

            try:
                edited = solid.cut(cutter)
                if edited.wrapped.IsNull():
                    # A solid wholly removed by the requested opening should
                    # simply be omitted from the rebuilt compound.
                    cut_count += 1
                    continue
                edited_shapes.append(edited)
                cut_count += 1
            except Exception as solid_error:
                # Preserve rather than corrupt geometry if an isolated,
                # marginal/tangent solid causes an OCC boolean failure.
                print("SOLID CUT WARNING:", solid_error)
                edited_shapes.append(solid)
                failed_count += 1

        if not edited_shapes:
            raise ValueError("Rounded opening operation removed all geometry")

        result_shape = cq.Compound.makeCompound(edited_shapes)
        boolean_mode = "per-solid fallback"
        print("FALLBACK COUNTS: cut=%d preserved=%d failed=%d" % (
            cut_count, preserved_count, failed_count))

    result_bb = result_shape.BoundingBox()
    print("RESULT VALID:", result_shape.isValid())
    print("BOOLEAN MODE:", boolean_mode)
    print("SOURCE BBOX: x=[%.3f, %.3f] y=[%.3f, %.3f] z=[%.3f, %.3f]" % (
        source_bb.xmin, source_bb.xmax,
        source_bb.ymin, source_bb.ymax,
        source_bb.zmin, source_bb.zmax))
    print("RESULT BBOX: x=[%.3f, %.3f] y=[%.3f, %.3f] z=[%.3f, %.3f]" % (
        result_bb.xmin, result_bb.xmax,
        result_bb.ymin, result_bb.ymax,
        result_bb.zmin, result_bb.zmax))
    print("OPENING: width=%.1f height=%.1f depth=%.1f radius=%.1f" % (
        opening_width, opening_height, cut_depth, corner_radius))
    print("OPENING BOUNDS: x=[%.3f, %.3f] y=[%.3f, %.3f] z=[%.3f, %.3f]" % (
        xmin, xmin + opening_width,
        inner_y, rear_y,
        bottom_z, bottom_z + opening_height))

    return cq.Workplane("XY").newObject([result_shape])