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

    # Locate the substantial rear-cover/housing solid using the geometry found
    # in the original STEP assembly. The model's rear assembly occupies the
    # high-Y end of its actual imported coordinate system.
    candidates = []
    for index, solid in enumerate(solids):
        bb = solid.BoundingBox()
        if bb.xlen > 250.0 and bb.zlen > 250.0 and bb.ymin > 350.0:
            candidates.append((solid.Volume(), index, solid, bb))

    if not candidates:
        print('SOLID COUNT:', len(solids))
        for index, solid in enumerate(solids):
            bb = solid.BoundingBox()
            if bb.xlen > 150.0 and bb.zlen > 150.0:
                print(
                    'LARGE SOLID %d: volume=%.3f bbox x=[%.3f, %.3f] '
                    'y=[%.3f, %.3f] z=[%.3f, %.3f]' % (
                        index, solid.Volume(), bb.xmin, bb.xmax,
                        bb.ymin, bb.ymax, bb.zmin, bb.zmax
                    )
                )
        raise ValueError('Unable to identify the rear-cover housing solid.')

    _, target_index, target, target_bb = max(candidates, key=lambda item: item[0])

    opening_width = 200.0
    opening_height = 100.0
    corner_radius = 10.0
    cut_depth = 30.0

    if target_bb.xlen < opening_width or target_bb.zlen < opening_height:
        raise ValueError(
            'The specified 200 x 100 mm opening does not fit the selected rear '
            'cover bounding box of %.3f x %.3f mm.' %
            (target_bb.xlen, target_bb.zlen)
        )

    # Center the opening horizontally. Set its bottom margin approximately
    # equal to the two lateral margins, as requested.
    x_center = 0.5 * (target_bb.xmin + target_bb.xmax)
    lateral_margin = 0.5 * (target_bb.xlen - opening_width)
    opening_bottom = target_bb.zmin + lateral_margin
    z_center = opening_bottom + 0.5 * opening_height

    if opening_bottom < target_bb.zmin or opening_bottom + opening_height > target_bb.zmax:
        raise ValueError(
            'The requested balanced lower placement does not fit vertically '
            'inside the selected rear cover.'
        )

    # The imported model's rear exterior is the high-Y face. Start just outside
    # it and extrude toward decreasing Y by 30 mm. This is geometrically the
    # inward direction for this STEP file despite the planning-stage semantic
    # axis convention.
    exterior_y = target_bb.ymax
    overlap_allowance = 0.10
    start_y = exterior_y + overlap_allowance
    cutter_length = cut_depth + overlap_allowance

    rear_plane = cq.Plane(
        origin=(x_center, start_y, z_center),
        xDir=(1.0, 0.0, 0.0),
        normal=(0.0, -1.0, 0.0)
    )

    # Construct an exact 200 x 100 mm rounded rectangle without applying a
    # Workplane fillet to a wire. It is the union of two rectangular prisms and
    # four radius-10 cylindrical corner prisms.
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
            corner_part = (
                cq.Workplane(rear_plane)
                .center(local_x, local_z)
                .circle(corner_radius)
                .extrude(cutter_length)
                .val()
            )
            cutter_parts.append(corner_part)

    cutter = cutter_parts[0]
    for part in cutter_parts[1:]:
        cutter = cutter.fuse(part)

    if not cutter.isValid():
        raise ValueError('The rounded-rectangle cutter is invalid.')

    original_volume = target.Volume()
    modified_target = target.cut(cutter)
    removed_volume = original_volume - modified_target.Volume()

    if removed_volume <= 1.0:
        raise ValueError(
            'The rounded-rectangle cutter did not materially intersect the '
            'selected rear-cover solid.'
        )

    expected_profile_area = (
        opening_width * opening_height
        - (4.0 - math.pi) * corner_radius * corner_radius
    )

    print('TOTAL IMPORTED SOLIDS:', len(solids))
    print('REAR COVER SOLID INDEX:', target_index)
    print(
        'REAR COVER BBOX: x=[%.3f, %.3f] y=[%.3f, %.3f] z=[%.3f, %.3f]' % (
            target_bb.xmin, target_bb.xmax,
            target_bb.ymin, target_bb.ymax,
            target_bb.zmin, target_bb.zmax
        )
    )
    print(
        'OPENING CENTER AT REAR SURFACE: x=%.3f y=%.3f z=%.3f' %
        (x_center, exterior_y, z_center)
    )
    print('OPENING: width=200 mm height=100 mm corner radius=10 mm depth=30 mm')
    print('LATERAL AND NOMINAL BOTTOM MARGIN: %.3f mm' % lateral_margin)
    print('REMOVED VOLUME: %.3f mm^3' % removed_volume)
    print('NOMINAL FULL-DEPTH CUTTER VOLUME: %.3f mm^3' %
          (expected_profile_area * cut_depth))

    rebuilt_solids = []
    for index, solid in enumerate(solids):
        if index == target_index:
            rebuilt_solids.extend(list(modified_target.Solids()))
        else:
            rebuilt_solids.append(solid)

    if not rebuilt_solids:
        raise ValueError('No solids remain after rebuilding the assembly.')

    result = cq.Compound.makeCompound(rebuilt_solids)
    if not result.isValid():
        raise ValueError('The edited assembly compound is invalid.')

    return cq.Workplane(obj=result)
