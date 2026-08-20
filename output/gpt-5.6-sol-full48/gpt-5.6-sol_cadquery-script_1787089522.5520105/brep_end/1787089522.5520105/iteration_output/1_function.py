def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args['input_file'])
    imported = cq.importers.importStep(input_file)
    shape = imported.val()
    solids = list(shape.Solids())

    # Identify the substantial rear-cover solid. In this STEP model it is the
    # wide, tall body occupying the extreme high-Y rear region.
    candidates = []
    for i, solid in enumerate(solids):
        bb = solid.BoundingBox()
        if bb.xlen > 250.0 and bb.zlen > 250.0 and bb.ymin > 350.0:
            candidates.append((solid.Volume(), i, solid, bb))

    if not candidates:
        raise ValueError('Unable to identify the wide rear-cover solid.')

    # Prefer the largest qualifying rear-cover body.
    _, target_index, target, target_bb = max(candidates, key=lambda item: item[0])

    opening_width = 200.0
    opening_height = 100.0
    corner_radius = 10.0
    cut_depth = 30.0

    if target_bb.xlen < opening_width or target_bb.zlen < opening_height:
        raise ValueError(
            'The specified 200 x 100 mm opening does not fit the rear cover: '
            'available bbox is %.3f x %.3f mm.' % (target_bb.xlen, target_bb.zlen)
        )

    # Center horizontally. Use the resulting lateral clearance as the desired
    # approximate bottom clearance, producing balanced side and bottom margins.
    x_center = (target_bb.xmin + target_bb.xmax) * 0.5
    lateral_clearance = (target_bb.xlen - opening_width) * 0.5
    opening_bottom = target_bb.zmin + lateral_clearance
    z_center = opening_bottom + opening_height * 0.5

    if opening_bottom < target_bb.zmin or opening_bottom + opening_height > target_bb.zmax:
        raise ValueError('Balanced lower placement does not fit within the rear cover.')

    # The visible exterior of this imported rear cover is its high-Y side.
    # Start just outside it and cut inward toward -Y. This follows the actual
    # STEP geometry while modifying only the S01 rear-cover body; separate rear
    # ventilation rails and slats remain untouched.
    exterior_y = target_bb.ymax
    start_y = exterior_y + 0.10
    cutter_length = cut_depth + 0.10

    rear_plane = cq.Plane(
        origin=(x_center, start_y, z_center),
        xDir=(1.0, 0.0, 0.0),
        normal=(0.0, -1.0, 0.0)
    )

    cutter = (
        cq.Workplane(rear_plane)
        .rect(opening_width, opening_height)
        .vertices()
        .fillet(corner_radius)
        .extrude(cutter_length)
        .val()
    )

    original_volume = target.Volume()
    modified_target = target.cut(cutter)
    removed_volume = original_volume - modified_target.Volume()

    if removed_volume <= 1.0:
        raise ValueError('Rounded-rectangle cutter did not materially intersect the rear cover.')

    expected_area = (
        opening_width * opening_height
        - (4.0 - 3.141592653589793) * corner_radius * corner_radius
    )
    print('REAR COVER SOLID INDEX:', target_index)
    print('REAR COVER BBOX: x=[%.3f, %.3f] y=[%.3f, %.3f] z=[%.3f, %.3f]' % (
        target_bb.xmin, target_bb.xmax, target_bb.ymin, target_bb.ymax,
        target_bb.zmin, target_bb.zmax))
    print('OPENING CENTER: x=%.3f y=%.3f z=%.3f' % (x_center, exterior_y, z_center))
    print('OPENING SIZE: 200 x 100 mm, radius=10 mm, depth=30 mm')
    print('REMOVED VOLUME: %.3f mm^3; nominal=%.3f mm^3' % (
        removed_volume, expected_area * cut_depth))

    rebuilt = []
    for i, solid in enumerate(solids):
        if i == target_index:
            rebuilt.extend(modified_target.Solids())
        else:
            rebuilt.append(solid)

    result = cq.Compound.makeCompound(rebuilt)
    if not result.isValid():
        raise ValueError('The edited assembly compound is invalid.')

    return cq.Workplane(obj=result)
