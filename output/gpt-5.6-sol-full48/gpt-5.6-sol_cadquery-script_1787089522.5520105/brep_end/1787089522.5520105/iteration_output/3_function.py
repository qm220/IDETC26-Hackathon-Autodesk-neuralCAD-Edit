def my_cad_function(args):
    import os
    import math
    import cadquery as cq

    input_file = os.path.expanduser(args['input_file'])
    imported = cq.importers.importStep(input_file)
    root_shape = imported.val()
    solids = list(root_shape.Solids())

    if not solids:
        raise ValueError('The imported STEP file contains no solids.')

    candidates = []
    for index, solid in enumerate(solids):
        bb = solid.BoundingBox()
        if bb.xlen > 250.0 and bb.zlen > 250.0 and bb.ymin > 350.0:
            candidates.append((solid.Volume(), index, solid, bb))

    if not candidates:
        raise ValueError('Unable to identify the rear-cover housing solid.')

    _, target_index, target, target_bb = max(candidates, key=lambda item: item[0])

    opening_width = 200.0
    opening_height = 100.0
    corner_radius = 10.0
    cut_depth = 30.0

    if target_bb.xlen < opening_width or target_bb.zlen < opening_height:
        raise ValueError('The specified 200 x 100 mm opening does not fit the rear cover.')

    x_center = 0.5 * (target_bb.xmin + target_bb.xmax)
    lateral_margin = 0.5 * (target_bb.xlen - opening_width)
    opening_bottom = target_bb.zmin + lateral_margin
    z_center = opening_bottom + 0.5 * opening_height

    exterior_y = target_bb.ymax
    overlap_allowance = 0.10
    cutter_length = cut_depth + overlap_allowance

    rear_plane = cq.Plane(
        origin=(x_center, exterior_y + overlap_allowance, z_center),
        xDir=(1.0, 0.0, 0.0),
        normal=(0.0, -1.0, 0.0)
    )

    cutter_parts = [
        cq.Workplane(rear_plane)
        .rect(opening_width - 2.0 * corner_radius, opening_height)
        .extrude(cutter_length)
        .val(),
        cq.Workplane(rear_plane)
        .rect(opening_width, opening_height - 2.0 * corner_radius)
        .extrude(cutter_length)
        .val()
    ]

    corner_x = 0.5 * opening_width - corner_radius
    corner_z = 0.5 * opening_height - corner_radius
    for local_x in (-corner_x, corner_x):
        for local_z in (-corner_z, corner_z):
            cutter_parts.append(
                cq.Workplane(rear_plane)
                .center(local_x, local_z)
                .circle(corner_radius)
                .extrude(cutter_length)
                .val()
            )

    cutter = cutter_parts[0]
    for part in cutter_parts[1:]:
        cutter = cutter.fuse(part)

    modified_target = target.cut(cutter)
    removed_volume = target.Volume() - modified_target.Volume()
    if removed_volume <= 1.0:
        raise ValueError('The opening cutter did not intersect the rear cover.')

    print('REAR COVER SOLID INDEX:', target_index)
    print('OPENING: 200 x 100 mm, corner radius 10 mm, depth 30 mm')
    print('LATERAL AND NOMINAL BOTTOM MARGIN: %.3f mm' % lateral_margin)
    print('REMOVED VOLUME: %.3f mm^3' % removed_volume)

    rebuilt_solids = []
    for index, solid in enumerate(solids):
        if index == target_index:
            rebuilt_solids.extend(list(modified_target.Solids()))
        else:
            rebuilt_solids.append(solid)

    result = cq.Compound.makeCompound(rebuilt_solids)
    if not result.isValid():
        raise ValueError('The edited assembly compound is invalid.')

    return cq.Workplane(obj=result)