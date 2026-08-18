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

    # Rear is the positive-Y end of this model. The usable appliance width is
    # approximately 300 mm, centered at x=-150 mm. A 200 mm opening therefore
    # leaves approximately equal 50 mm side margins. Placing its lower edge at
    # z=50 mm gives a similar bottom margin.
    opening_width = 200.0
    opening_height = 100.0
    corner_radius = 10.0
    recess_depth = 30.0
    center_x = (bbox.xmin + bbox.xmax) * 0.5
    center_z = 100.0

    # The principal rear exterior field is near y=415 mm. Extend the tool from
    # outside all rear-cover bulges to y=385 mm, which is 30 mm inward from that
    # principal rear field. This also cleanly trims intersecting grille ribs.
    rear_reference_y = 415.0
    tool_outer_y = bbox.ymax + 5.0
    tool_inner_y = rear_reference_y - recess_depth
    tool_length = tool_outer_y - tool_inner_y

    rear_plane = cq.Plane(
        origin=(center_x, tool_outer_y, center_z),
        xDir=(1, 0, 0),
        normal=(0, -1, 0)
    )
    cutter_wp = (
        cq.Workplane(rear_plane)
        .rect(opening_width, opening_height)
        .vertices()
        .fillet(corner_radius)
        .extrude(tool_length)
    )
    cutter = cutter_wp.val()

    cb = cutter.BoundingBox()
    print('CUTTER: 200 x 100 mm rounded rectangle, radius 10 mm')
    print('CUTTER BBOX: x=[%.2f, %.2f] y=[%.2f, %.2f] z=[%.2f, %.2f]' % (
        cb.xmin, cb.xmax, cb.ymin, cb.ymax, cb.zmin, cb.zmax))
    print('NOMINAL RECESS DEPTH:', recess_depth, 'mm from y=', rear_reference_y)

    result_solids = []
    modified_count = 0
    split_count = 0

    for index, solid in enumerate(source_shape.Solids()):
        sb = solid.BoundingBox()
        overlaps = not (
            sb.xmax < cb.xmin or sb.xmin > cb.xmax or
            sb.ymax < cb.ymin or sb.ymin > cb.ymax or
            sb.zmax < cb.zmin or sb.zmin > cb.zmax
        )

        if not overlaps:
            result_solids.append(solid)
            continue

        original_volume = solid.Volume()
        try:
            cut_shape = solid.cut(cutter)
            cut_solids = list(cut_shape.Solids())
            remaining_volume = sum(s.Volume() for s in cut_solids)

            if original_volume - remaining_volume > 1.0e-4:
                modified_count += 1
                if len(cut_solids) > 1:
                    split_count += 1
                print('CUT SOLID %02d: removed %.3f mm^3, fragments=%d' % (
                    index, original_volume - remaining_volume, len(cut_solids)))
                result_solids.extend(cut_solids)
            else:
                result_solids.append(solid)
        except Exception as exc:
            print('WARNING: cut failed for solid %02d: %s' % (index, str(exc)))
            result_solids.append(solid)

    result_shape = cq.Compound.makeCompound(result_solids)
    print('MODIFIED SOURCE SOLIDS:', modified_count)
    print('SPLIT SOURCE SOLIDS:', split_count)
    print('RESULT SOLIDS:', len(result_shape.Solids()), 'FACES:', len(result_shape.Faces()))
    print('RESULT VALID:', result_shape.isValid())

    return cq.Workplane('XY').newObject([result_shape])