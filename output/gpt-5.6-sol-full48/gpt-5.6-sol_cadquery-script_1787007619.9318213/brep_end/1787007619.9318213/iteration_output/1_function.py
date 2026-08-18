def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    base_shape = model.val()

    bbox = base_shape.BoundingBox()
    cx = (bbox.xmin + bbox.xmax) / 2.0
    cy = (bbox.ymin + bbox.ymax) / 2.0
    bottom_z = bbox.zmin
    x_size = bbox.xmax - bbox.xmin
    y_size = bbox.ymax - bbox.ymin

    flange_width = 2.0
    flange_thickness = 0.5
    outer_x = x_size + 2.0 * flange_width
    outer_y = y_size + 2.0 * flange_width
    opening_x = 1.6
    opening_y = 5.6
    flange_bottom = bottom_z - flange_thickness

    outer_plate = (
        cq.Workplane("XY")
        .workplane(offset=flange_bottom)
        .center(cx, cy)
        .rect(outer_x, outer_y)
        .extrude(flange_thickness)
    )
    central_opening = (
        cq.Workplane("XY")
        .workplane(offset=flange_bottom - 0.05)
        .center(cx, cy)
        .rect(opening_x, opening_y)
        .extrude(flange_thickness + 0.10)
    )
    flange = outer_plate.cut(central_opening)

    hole_diameter = 0.5
    edge_to_center = 0.6
    hole_x = outer_x / 2.0 - edge_to_center
    hole_y = outer_y / 2.0 - edge_to_center
    hole_points = [
        (cx - hole_x, cy - hole_y),
        (cx + hole_x, cy - hole_y),
        (cx - hole_x, cy + hole_y),
        (cx + hole_x, cy + hole_y),
    ]
    hole_cutters = (
        cq.Workplane("XY")
        .workplane(offset=flange_bottom - 0.05)
        .pushPoints(hole_points)
        .circle(hole_diameter / 2.0)
        .extrude(flange_thickness + 0.10)
    )
    flange = flange.cut(hole_cutters)
    return model.union(flange)
