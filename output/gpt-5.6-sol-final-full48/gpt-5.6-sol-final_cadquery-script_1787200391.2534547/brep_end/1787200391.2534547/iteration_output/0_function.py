def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    original = cq.importers.importStep(input_file)

    # Existing body footprint: X = +/-1 mm, Y = +/-3 mm.
    # Extend the flange 2 mm outward from every body edge.
    flange_outer_x = 6.0
    flange_outer_y = 10.0
    cavity_x = 1.6
    cavity_y = 5.6
    flange_thickness = 0.5
    flange_top_z = -0.75
    flange_bottom_z = flange_top_z - flange_thickness

    # Form an open-center rectangular flange below the existing bottom face.
    outer = (
        cq.Workplane("XY")
        .box(flange_outer_x, flange_outer_y, flange_thickness)
        .translate((0, 0, (flange_top_z + flange_bottom_z) / 2.0))
    )
    center_opening = (
        cq.Workplane("XY")
        .box(cavity_x, cavity_y, flange_thickness + 0.2)
        .translate((0, 0, (flange_top_z + flange_bottom_z) / 2.0))
    )
    flange = outer.cut(center_opening)

    # Hole centers are 0.6 mm from each pair of adjacent outer edges.
    hole_centers = [
        (-2.4, -4.4),
        (-2.4,  4.4),
        ( 2.4, -4.4),
        ( 2.4,  4.4),
    ]
    hole_cutters = (
        cq.Workplane("XY", origin=(0, 0, flange_bottom_z - 0.1))
        .pushPoints(hole_centers)
        .circle(0.25)
        .extrude(flange_thickness + 0.2)
    )
    flange = flange.cut(hole_cutters)

    # Join the flange to the annular bottom rim of the imported saddle.
    result = original.union(flange).clean()

    shape = result.val()
    bbox = shape.BoundingBox()
    print(f"Result valid: {shape.isValid()}")
    print(f"Result solids: {len(shape.Solids())}")
    print(f"Bounding box: X[{bbox.xmin:.3f}, {bbox.xmax:.3f}], "
          f"Y[{bbox.ymin:.3f}, {bbox.ymax:.3f}], "
          f"Z[{bbox.zmin:.3f}, {bbox.zmax:.3f}]")
    print("Added 0.5 mm thick open-center flange and four diameter-0.5 mm mounting holes.")
    return result