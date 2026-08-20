def my_cad_function(args):
    import os
    import cadquery as cq

    model = cq.importers.importStep(os.path.expanduser(args["input_file"]))
    result = model.val()

    bore_center_y = 3.51
    bore_center_z = 2.943179
    bore_radius = 1.7 / 2.0

    through_bore = cq.Solid.makeCylinder(
        bore_radius,
        4.0,
        cq.Vector(4.2, bore_center_y, bore_center_z),
        cq.Vector(1, 0, 0)
    )
    result = result.cut(through_bore)

    left_inner_x = 5.29764
    right_inner_x = 6.94764
    groove_depth = 0.1
    groove_width = 0.1
    groove_radii = (1.00, 1.20)

    def annular_cutter(x_start, depth, mean_radius):
        outer_radius = mean_radius + groove_width / 2.0
        inner_radius = mean_radius - groove_width / 2.0
        outer = cq.Solid.makeCylinder(
            outer_radius,
            depth,
            cq.Vector(x_start, bore_center_y, bore_center_z),
            cq.Vector(1, 0, 0)
        )
        inner = cq.Solid.makeCylinder(
            inner_radius,
            depth,
            cq.Vector(x_start, bore_center_y, bore_center_z),
            cq.Vector(1, 0, 0)
        )
        return outer.cut(inner)

    for radius in groove_radii:
        cutter = annular_cutter(
            left_inner_x - groove_depth,
            groove_depth + 0.01,
            radius
        )
        result = result.cut(cutter)

    for radius in groove_radii:
        cutter = annular_cutter(
            right_inner_x - 0.01,
            groove_depth + 0.01,
            radius
        )
        result = result.cut(cutter)

    print("CONNECTING_HOLE_DIAMETER", 1.7)
    print("GROOVE_WIDTH", groove_width)
    print("GROOVE_DEPTH", groove_depth)
    print("GROOVE_COUNT_PER_INNER_FACE", len(groove_radii))
    print("RESULT_VALID", result.isValid())

    return cq.Workplane("XY").newObject([result])