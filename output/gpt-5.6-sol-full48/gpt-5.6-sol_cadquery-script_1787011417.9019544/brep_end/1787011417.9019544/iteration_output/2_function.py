def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args['input_file'])
    model = cq.importers.importStep(input_file)
    source_shape = model.val()
    bbox = source_shape.BoundingBox()

    print('SOURCE VALID:', source_shape.isValid())
    print('SOURCE SOLIDS:', len(source_shape.Solids()), 'FACES:', len(source_shape.Faces()))
    print('SOURCE BBOX: x=[%.2f, %.2f] y=[%.2f, %.2f] z=[%.2f, %.2f]' % (
        bbox.xmin, bbox.xmax, bbox.ymin, bbox.ymax,
        bbox.zmin, bbox.zmax))

    # Requested opening dimensions in millimetres.
    opening_width = 200.0
    opening_height = 100.0
    corner_radius = 10.0
    recess_depth = 30.0

    # The machine is approximately 312 mm wide. Horizontal centering leaves
    # nearly equal side margins. A lower edge 50 mm above the overall bottom
    # approximately matches those margins.
    center_x = (bbox.xmin + bbox.xmax) * 0.5
    bottom_margin = 50.0
    center_z = bbox.zmin + bottom_margin + opening_height * 0.5

    # Positive Y is the back. Start outside the complete rear assembly and cut
    # inward 30 mm from the nominal rear-cover exterior field at y=415 mm.
    rear_reference_y = 415.0
    tool_outer_y = bbox.ymax + 5.0
    tool_inner_y = rear_reference_y - recess_depth
    tool_length = tool_outer_y - tool_inner_y

    rear_plane = cq.Plane(
        origin=(center_x, tool_outer_y, center_z),
        xDir=(1, 0, 0),
        normal=(0, -1, 0)
    )

    # Construct the exact rounded rectangle as the union of two rectangular
    # prisms and four cylindrical corner prisms. Keeping the primitives
    # separate avoids the invalid Workplane.vertices().fillet() operation that
    # failed in the previous iteration. Sequential subtraction is equivalent
    # to subtracting their union.
    cutter_parts = []
    cutter_parts.append(
        cq.Workplane(rear_plane)
        .rect(opening_width - 2.0 * corner_radius, opening_height)
        .extrude(tool_length)
        .val()
    )
    cutter_parts.append(
        cq.Workplane(rear_plane)
        .rect(opening_width, opening_height - 2.0 * corner_radius)
        .extrude(tool_length)
        .val()
    )

    corner_x = opening_width * 0.5 - corner_radius
    corner_z = opening_height * 0.5 - corner_radius
    for dx in (-corner_x, corner_x):
        for dz in (-corner_z, corner_z):
            corner_tool = (
                cq.Workplane(rear_plane)
                .center(dx, dz)
                .circle(corner_radius)
                .extrude(tool_length)
                .val()
            )
            cutter_parts.append(corner_tool)

    cutter_compound = cq.Compound.makeCompound(cutter_parts)
    cb = cutter_compound.BoundingBox()
    print('OPENING: width=200.00 height=100.00 radius=10.00 depth=30.00 mm')
    print('OPENING CENTER: x=%.2f z=%.2f' % (center_x, center_z))
    print('CUTTER BBOX: x=[%.2f, %.2f] y=[%.2f, %.2f] z=[%.2f, %.2f]' % (
        cb.xmin, cb.xmax, cb.ymin, cb.ymax, cb.zmin, cb.zmax))

    result_solids = []
    modified_count = 0
    split_count = 0
    total_removed = 0.0

    for index, solid in enumerate(source_shape.Solids()):
        sb = solid.BoundingBox()
        overlaps_envelope = not (
            sb.xmax < cb.xmin or sb.xmin > cb.xmax or
            sb.ymax < cb.ymin or sb.ymin > cb.ymax or
            sb.zmax < cb.zmin or sb.zmin > cb.zmax
        )

        # Limit the edit to rear-facing cover/grille components. This prevents
        # the 30 mm envelope from automatically cutting the structural U-frame
        # or internal chassis. Rear pieces extending to the nominal exterior
        # field remain eligible, including grille ribs crossing the opening.
        is_rear_component = sb.ymax >= rear_reference_y - 2.0

        if not overlaps_envelope or not is_rear_component:
            result_solids.append(solid)
            continue

        original_volume = solid.Volume()
        edited_shape = solid
        try:
            for cutter_part in cutter_parts:
                edited_shape = edited_shape.cut(cutter_part)

            edited_solids = list(edited_shape.Solids())
            remaining_volume = sum(item.Volume() for item in edited_solids)
            removed_volume = original_volume - remaining_volume

            if removed_volume > 1.0e-4:
                modified_count += 1
                total_removed += removed_volume
                if len(edited_solids) > 1:
                    split_count += 1
                print('CUT REAR SOLID %02d: removed %.3f mm^3, fragments=%d, ymax=%.2f' % (
                    index, removed_volume, len(edited_solids), sb.ymax))
                result_solids.extend(edited_solids)
            else:
                result_solids.append(solid)
        except Exception as exc:
            print('WARNING: cut failed for rear solid %02d: %s' % (index, str(exc)))
            result_solids.append(solid)

    result_shape = cq.Compound.makeCompound(result_solids)
    print('MODIFIED REAR SOLIDS:', modified_count)
    print('SPLIT REAR SOLIDS:', split_count)
    print('TOTAL REMOVED VOLUME: %.3f mm^3' % total_removed)
    print('RESULT SOLIDS:', len(result_shape.Solids()), 'FACES:', len(result_shape.Faces()))
    print('RESULT VALID:', result_shape.isValid())

    if modified_count == 0:
        print('WARNING: No rear solids intersected the selected opening envelope.')

    return cq.Workplane('XY').newObject([result_shape])