def my_cad_function(args):
    os = __import__('os')
    math = __import__('math')

    input_file = os.path.expanduser(args['input_file'])
    model = cq.importers.importStep(input_file)
    shape = model.val()
    solids = shape.Solids()

    if len(solids) < 2:
        raise ValueError(f'Expected two solids in the source model, found {len(solids)}')

    # The sprocket axis is global Y. Preserve the separate splined hub and
    # modify only the wheel solid containing the rounded chain-sprocket teeth.
    hub = solids[0]
    wheel = solids[1]

    # Remove the original rounded/scalloped perimeter while retaining the
    # spoke network, web, hub transition, and inner portion of the rim.
    preserve_radius = 46.70
    keeper = cq.Solid.makeCylinder(
        preserve_radius,
        20.0,
        cq.Vector(0, -10.0, 0),
        cq.Vector(0, 1, 0),
    )
    preserved_wheel = wheel.intersect(keeper)

    # Replacement literal straight-sided spur teeth. The tooth count and
    # overall envelope are retained from the source perimeter.
    tooth_count = 54
    ring_inner_radius = 45.50
    root_radius = 49.00
    tooth_base_radius = 48.50
    tip_radius = 56.50
    face_y_front = 3.175
    face_width = 6.350

    # Build a constant-width root annulus that overlaps the preserved wheel.
    outer_root = cq.Solid.makeCylinder(
        root_radius,
        face_width,
        cq.Vector(0, face_y_front, 0),
        cq.Vector(0, -1, 0),
    )
    inner_relief = cq.Solid.makeCylinder(
        ring_inner_radius,
        face_width + 0.40,
        cq.Vector(0, face_y_front + 0.20, 0),
        cq.Vector(0, -1, 0),
    )
    spur_ring = outer_root.cut(inner_relief)

    pitch_angle = 360.0 / tooth_count
    root_half_angle = pitch_angle * 0.37
    tip_half_angle = pitch_angle * 0.19

    def polar_point(radius, angle_degrees):
        angle = math.radians(angle_degrees)
        return (
            radius * math.cos(angle),
            radius * math.sin(angle),
        )

    # Trapezoidal radial profile with straight flanks and a straight tip chord.
    tooth_profile = [
        polar_point(tooth_base_radius, -root_half_angle),
        polar_point(tip_radius, -tip_half_angle),
        polar_point(tip_radius, tip_half_angle),
        polar_point(tooth_base_radius, root_half_angle),
    ]

    tooth_plane = cq.Plane(
        origin=(0, face_y_front, 0),
        xDir=(1, 0, 0),
        normal=(0, -1, 0),
    )
    tooth_0 = (
        cq.Workplane(tooth_plane)
        .polyline(tooth_profile)
        .close()
        .extrude(face_width)
        .val()
    )

    teeth = []
    for index in range(tooth_count):
        teeth.append(
            tooth_0.rotate(
                cq.Vector(0, 0, 0),
                cq.Vector(0, 1, 0),
                index * pitch_angle,
            )
        )

    replacement_perimeter = spur_ring.fuse(*teeth)
    modified_wheel = preserved_wheel.fuse(replacement_perimeter)

    if not modified_wheel.isValid():
        raise ValueError('The modified wheel failed solid-validity checking')

    # Keep the original two-solid organization and preserve the spline exactly.
    result_shape = cq.Compound.makeCompound([hub, modified_wheel])
    if not result_shape.isValid():
        raise ValueError('The resulting compound failed validity checking')

    result = cq.Workplane('XY').newObject([result_shape])
    bb = result_shape.BoundingBox()

    print(f'Source solids: {len(solids)}')
    print(f'Replacement spur teeth: {tooth_count}')
    print(
        f'Tooth face range: Y={face_y_front - face_width:.3f} '
        f'to {face_y_front:.3f}'
    )
    print(f'Root diameter: {2.0 * root_radius:.3f}')
    print(f'Tip diameter: {2.0 * tip_radius:.3f}')
    print(f'Result valid: {result_shape.isValid()}')
    print(f'Result solids: {len(result_shape.Solids())}')
    print(
        f'Result bbox size: '
        f'({bb.xlen:.3f}, {bb.ylen:.3f}, {bb.zlen:.3f})'
    )

    return result