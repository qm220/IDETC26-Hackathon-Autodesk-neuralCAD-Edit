def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args['input_file'])
    model = cq.importers.importStep(input_file)
    original = model.val()

    axis_y = 3.5100
    axis_z = 2.9432
    hole_radius = 0.85

    hole_cutter = (
        cq.Workplane('YZ', origin=(4.50, axis_y, axis_z))
        .circle(hole_radius)
        .extrude(3.20)
    )
    result = cq.Workplane(obj=original).cut(hole_cutter)

    left_inner_x = 5.2976
    right_inner_x = 6.9476
    groove_depth = 0.10
    groove_width = 0.075
    groove_r_inner = 1.00
    groove_r_outer = 1.30
    groove_length = groove_r_outer - groove_r_inner
    groove_mid_radius = (groove_r_inner + groove_r_outer) / 2.0
    groove_count = 12
    overlap = 0.005

    left_seed = (
        cq.Workplane('YZ', origin=(left_inner_x + overlap, axis_y, axis_z))
        .center(groove_mid_radius, 0.0)
        .rect(groove_length, groove_width)
        .extrude(-(groove_depth + 2.0 * overlap))
    )

    right_seed = (
        cq.Workplane('YZ', origin=(right_inner_x - overlap, axis_y, axis_z))
        .center(groove_mid_radius, 0.0)
        .rect(groove_length, groove_width)
        .extrude(groove_depth + 2.0 * overlap)
    )

    axis_start = (0.0, axis_y, axis_z)
    axis_end = (1.0, axis_y, axis_z)
    left_grooves = None
    right_grooves = None

    for i in range(groove_count):
        angle = 360.0 * i / groove_count
        lg = left_seed.rotate(axis_start, axis_end, angle)
        rg = right_seed.rotate(axis_start, axis_end, angle)
        left_grooves = lg if left_grooves is None else left_grooves.union(lg)
        right_grooves = rg if right_grooves is None else right_grooves.union(rg)

    result = result.cut(left_grooves).cut(right_grooves)
    final_shape = result.val()

    print('EDIT connecting_hole_diameter=1.7000 mm')
    print('EDIT hole_axis=(X; y=%.4f, z=%.4f)' % (axis_y, axis_z))
    print('EDIT grooves depth=%.4f mm count_per_cheek=%d radial_limits=(%.3f, %.3f)' %
          (groove_depth, groove_count, groove_r_inner, groove_r_outer))
    print('VALID', final_shape.isValid())
    print('SOLIDS', len(final_shape.Solids()), 'FACES', len(final_shape.Faces()),
          'VOLUME %.6f' % final_shape.Volume())

    return result