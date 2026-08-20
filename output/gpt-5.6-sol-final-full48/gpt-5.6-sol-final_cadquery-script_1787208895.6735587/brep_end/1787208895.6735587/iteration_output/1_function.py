def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)

    axis_x = 80.0
    axis_y = 17.0
    axis_start = (axis_x, axis_y, 0.0)
    axis_end = (axis_x, axis_y, 1.0)

    radial_body = None
    for angle in range(0, 360, 45):
        occurrence = imported.rotate(axis_start, axis_end, float(angle))
        radial_body = occurrence if radial_body is None else radial_body.union(occurrence)

    outer_boss = (
        cq.Workplane("XY", origin=(0.0, 0.0, 6.0))
        .center(axis_x, axis_y)
        .circle(7.0)
        .extrude(9.0)
    )

    root = (
        cq.Workplane("XY", origin=(0.0, 0.0, 6.0))
        .center(axis_x, axis_y)
        .circle(8.0)
        .workplane(offset=1.25)
        .circle(7.0)
        .loft(combine=True)
    )

    result = radial_body.union(root).union(outer_boss)

    bore = (
        cq.Workplane("XY", origin=(0.0, 0.0, 6.0))
        .center(axis_x, axis_y)
        .circle(5.0)
        .extrude(9.1)
    )
    result = result.cut(bore)

    print("Created 8 radial arm instances at 45-degree spacing.")
    print("Added common flat-end bearing: outer radius 7, bore radius 5, height 9.")
    return result