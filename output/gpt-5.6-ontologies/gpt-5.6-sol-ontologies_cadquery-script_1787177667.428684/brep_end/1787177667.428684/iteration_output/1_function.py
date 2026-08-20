def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    # Dimensions are in millimetres. The opening is interpreted as 200 mm
    # horizontal by 100 mm vertical, with 10 mm corner radii and a 30 mm
    # blind depth into the rear (+Y) surface.
    opening_width = 200.0
    opening_height = 100.0
    corner_radius = 10.0
    cut_depth = 30.0

    # The main rear surface is approximately Y=409 mm and the machine spans
    # X=-300..0 mm. Centering the 200 mm opening leaves about 50 mm at each
    # side. A bottom edge at Z=50 mm gives approximately the same clearance
    # from the machine bottom.
    center_x = -150.0
    bottom_z = 50.0
    rear_y = 409.0
    inner_y = rear_y - cut_depth
    outside_overshoot = 6.0
    cutter_length = cut_depth + outside_overshoot

    xmin = center_x - opening_width / 2.0
    x_inner_min = xmin + corner_radius
    z_inner_min = bottom_z + corner_radius

    # Construct an exact rounded rectangle as the union of two overlapping
    # rectangular prisms and four corner cylinders. All cutters extend along
    # +Y from the 30 mm-deep floor through the exterior rear surface.
    cutters = [
        cq.Solid.makeBox(
            opening_width - 2.0 * corner_radius,
            cutter_length,
            opening_height,
            cq.Vector(x_inner_min, inner_y, bottom_z)
        ),
        cq.Solid.makeBox(
            opening_width,
            cutter_length,
            opening_height - 2.0 * corner_radius,
            cq.Vector(xmin, inner_y, z_inner_min)
        )
    ]

    corner_xs = [
        center_x - opening_width / 2.0 + corner_radius,
        center_x + opening_width / 2.0 - corner_radius
    ]
    corner_zs = [
        bottom_z + corner_radius,
        bottom_z + opening_height - corner_radius
    ]

    for x in corner_xs:
        for z in corner_zs:
            cutters.append(
                cq.Solid.makeCylinder(
                    corner_radius,
                    cutter_length,
                    cq.Vector(x, inner_y, z),
                    cq.Vector(0, 1, 0)
                )
            )

    result_shape = shape
    for cutter in cutters:
        result_shape = result_shape.cut(cutter)

    bb = result_shape.BoundingBox()
    print("RESULT VALID:", result_shape.isValid())
    print("RESULT BBOX: x=[%.3f, %.3f] y=[%.3f, %.3f] z=[%.3f, %.3f]" % (
        bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax))
    print("OPENING: width=%.1f height=%.1f depth=%.1f radius=%.1f" % (
        opening_width, opening_height, cut_depth, corner_radius))
    print("OPENING BOUNDS: x=[%.1f, %.1f] y=[%.1f, %.1f] z=[%.1f, %.1f]" % (
        xmin, xmin + opening_width, inner_y, rear_y,
        bottom_z, bottom_z + opening_height))

    return cq.Workplane("XY").newObject([result_shape])