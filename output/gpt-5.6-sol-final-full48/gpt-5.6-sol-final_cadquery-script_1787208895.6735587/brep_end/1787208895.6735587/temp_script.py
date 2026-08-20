def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)

    # Circular-pattern axis: center of the new bearing at the square end.
    axis_x = 80.0
    axis_y = 17.0
    axis_start = (axis_x, axis_y, 0.0)
    axis_end = (axis_x, axis_y, 1.0)

    # Pattern the complete existing body eight times at 45-degree increments.
    # The occurrences are consolidated into one radial solid where they overlap.
    radial_body = None
    for angle in range(0, 360, 45):
        occurrence = imported.rotate(axis_start, axis_end, float(angle))
        if radial_body is None:
            radial_body = occurrence
        else:
            radial_body = radial_body.union(occurrence)

    # Add one common hollow cylindrical bearing at the pattern center. The outer
    # diameter and bore match the existing nominal R7/R5 bearing dimensions.
    outer_boss = (
        cq.Workplane("XY", origin=(0.0, 0.0, 6.0))
        .center(axis_x, axis_y)
        .circle(7.0)
        .extrude(9.0)
    )

    # A shallow load-spreading root surrounds the cylindrical boss while keeping
    # the principal bearing wall at radius 7.
    root = (
        cq.Workplane("XY", origin=(0.0, 0.0, 6.0))
        .center(axis_x, axis_y)
        .circle(8.0)
        .workplane(offset=1.25)
        .circle(7.0)
        .loft(combine=True)
    )

    result = radial_body.union(root).union(outer_boss)

    # Form the blind R5 socket. It terminates at the original arm top plane z=6,
    # preserving the arm plate beneath it as the planar socket floor.
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
