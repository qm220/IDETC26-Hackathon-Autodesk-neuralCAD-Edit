def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()
    solids = shape.Solids()

    if len(solids) < 2:
        raise ValueError(f"Expected two solids in the source model, found {len(solids)}")

    # The source sprocket rotates about the global Y axis. SOLID 0 is the
    # splined hub and SOLID 1 is the wheel, rim, and rounded chain teeth.
    hub = solids[0]
    wheel = solids[1]

    # Preserve the wheel geometry inward of the original rim while removing
    # the rounded/scalloped chain-tooth perimeter and its axial bulges.
    axis_origin = cq.Vector(0, -10.0, 0)
    axis_dir = cq.Vector(0, 1, 0)
    preserve_radius = 46.70
    radial_keeper = cq.Solid.makeCylinder(
        preserve_radius, 20.0, axis_origin, axis_dir
    )
    preserved_wheel = wheel.intersect(radial_keeper)

    # Replacement straight spur-tooth dimensions, inferred from the existing
    # 54-position perimeter and its approximately 113 mm outside diameter.
    tooth_count = 54
    ring_inner_radius = 45.50
    root_radius = 49.00
    tooth_base_radius = 48.50
    tip_radius = 56.50
    face_y_front = 3.175
    face_width = 6.350

    outer_root = cq.Solid.makeCylinder(
        root_radius,
        face_width,
        cq.Vector(0, face_y_front, 0),
        cq.Vector(0, -1, 0),
    )
    inner_relief = cq.Solid.makeCylinder(
        ring_inner_radius,
        face_width + 0.4,
        cq.Vector(0, face_y_front + 0.2, 0),
        cq.Vector(0, -1, 0),
    )
    spur_ring = outer_root.cut(inner_relief)

    # A constant-section trapezoidal tooth is extruded parallel to the gear
    # axis. All profile edges and axial tooth edges are straight, with no
    # fillets or rounded chain pockets.
    pitch_angle = 360.0 / tooth_count
    root_half_angle = pitch_angle * 0.37
    tip_half_angle = pitch_angle * 0.19

    def polar_point(radius, angle_degrees):
        angle = math.radians(angle_degrees)
        return (radius * math.cos(angle), radius * math.sin(angle))

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
        angle = index * pitch_angle
        teeth.append(
            tooth_0.rotate(
                cq.Vector(0, 0, 0),
                cq.Vector(0, 1, 0),
                angle,
            )
        )

    replacement_gear = spur_ring.fuse(*teeth)
    modified_wheel = preserved_wheel.fuse(replacement_gear)

    if not modified_wheel.isValid():
        raise ValueError("The modified wheel failed solid-validity checking")

    # Retain the separate original splined hub exactly as supplied and replace
    # only the outer perimeter of the wheel solid.
    result_shape = cq.Compound.makeCompound([hub, modified_wheel])
    result = cq.Workplane("XY").newObject([result_shape])

    bb = result_shape.BoundingBox()
    print(f"Source solids: {len(solids)}")
    print(f"Replacement teeth: {tooth_count}")
    print(f"Spur tooth face range: Y={face_y_front - face_width:.3f} to {face_y_front:.3f}")
    print(f"Root diameter: {2 * root_radius:.3f}; tip diameter: {2 * tip_radius:.3f}")
    print(f"Result valid: {result_shape.isValid()}")
    print(f"Result solids: {len(result_shape.Solids())}")
    print(f"Result bbox size: ({bb.xlen:.3f}, {bb.ylen:.3f}, {bb.zlen:.3f})")

    return result