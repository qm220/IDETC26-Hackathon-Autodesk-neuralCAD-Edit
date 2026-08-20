def my_cad_function(args):
    import os
    import math
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    result = model.val() if hasattr(model, "val") else model

    bbox = result.BoundingBox()
    end_x = bbox.xmax
    axis_y = 0.5 * (11.0 + 23.0)
    axis_z = 0.5 * (2.0 + 6.0)

    instance_count = 8
    pattern_radius = 1.40
    bearing_outer_radius = 0.50
    bearing_inner_radius = 0.24
    bearing_length = 3.50
    axis_direction = cq.Vector(1.0, 0.0, 0.0)

    for index in range(instance_count):
        angle = 2.0 * math.pi * index / instance_count
        center_y = axis_y + pattern_radius * math.cos(angle)
        center_z = axis_z + pattern_radius * math.sin(angle)
        base = cq.Vector(end_x, center_y, center_z)

        outer = cq.Solid.makeCylinder(
            bearing_outer_radius,
            bearing_length,
            base,
            axis_direction
        )
        bore = cq.Solid.makeCylinder(
            bearing_inner_radius,
            bearing_length,
            base,
            axis_direction
        )
        result = result.fuse(outer.cut(bore))

    try:
        result = result.clean()
    except Exception:
        pass

    return cq.Workplane("XY").newObject([result])