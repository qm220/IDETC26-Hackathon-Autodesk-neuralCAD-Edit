def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    base_shape = model.val()

    # Extract the existing model envelope to locate the flat bottom surface.
    bbox = base_shape.BoundingBox()
    cx = (bbox.xmin + bbox.xmax) / 2.0
    cy = (bbox.ymin + bbox.ymax) / 2.0
    bottom_z = bbox.zmin
    x_size = bbox.xmax - bbox.xmin
    y_size = bbox.ymax - bbox.ymin

    print("Input valid:", base_shape.isValid())
    print("Input faces:", len(base_shape.Faces()))
    print("Input bbox: x=[%.4f, %.4f], y=[%.4f, %.4f], z=[%.4f, %.4f]" %
          (bbox.xmin, bbox.xmax, bbox.ymin, bbox.ymax, bbox.zmin, bbox.zmax))

    # The supplied part is 2 mm across x and 6 mm along y. The mounting flange
    # extends outward by 2 mm from every original outer edge.
    flange_width = 2.0
    flange_thickness = 0.5
    outer_x = x_size + 2.0 * flange_width
    outer_y = y_size + 2.0 * flange_width

    # Preserve the existing central cavity mouth (nominally 1.6 x 5.6 mm).
    opening_x = 1.6
    opening_y = 5.6

    # Build the flange from its lower face upward so its top starts exactly on
    # the existing flat bottom surface.
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

    # Four diameter 0.5 mm mounting holes. Hole centers are 0.6 mm inward from
    # each pair of adjacent outer flange edges.
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

    # Fuse the flange to the imported support shell.
    result = model.union(flange)
    result_shape = result.val()
    result_bbox = result_shape.BoundingBox()
    print("Flange outer size: %.4f x %.4f mm" % (outer_x, outer_y))
    print("Flange z range: %.4f to %.4f mm" % (flange_bottom, bottom_z))
    print("Hole centers:", hole_points)
    print("Result valid:", result_shape.isValid())
    print("Result solids:", len(result_shape.Solids()))
    print("Result bbox: x=[%.4f, %.4f], y=[%.4f, %.4f], z=[%.4f, %.4f]" %
          (result_bbox.xmin, result_bbox.xmax, result_bbox.ymin,
           result_bbox.ymax, result_bbox.zmin, result_bbox.zmax))
    return result