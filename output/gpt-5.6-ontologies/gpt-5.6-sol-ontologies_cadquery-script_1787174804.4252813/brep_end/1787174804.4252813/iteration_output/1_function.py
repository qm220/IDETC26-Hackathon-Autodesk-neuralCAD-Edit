def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    bb = shape.BoundingBox()
    z_bottom = bb.zmin

    # The flange projects 2 mm beyond every outer edge of the existing
    # rectangular bottom footprint.
    flange_width = 2.0
    flange_thickness = 0.5
    outer_x = (bb.xmax - bb.xmin) + 2.0 * flange_width
    outer_y = (bb.ymax - bb.ymin) + 2.0 * flange_width
    center_x = 0.5 * (bb.xmin + bb.xmax)
    center_y = 0.5 * (bb.ymin + bb.ymax)

    # Recover the opening in the existing flat bottom face so that the
    # underside cavity/central region remains open through the flange.
    bottom_face = None
    for face in shape.Faces():
        fbb = face.BoundingBox()
        if (
            face.geomType() == "PLANE"
            and abs(fbb.zmin - z_bottom) < 1e-7
            and abs(fbb.zmax - z_bottom) < 1e-7
            and len(face.Wires()) >= 2
        ):
            bottom_face = face
            break

    if bottom_face is None:
        raise ValueError("Could not identify the flat annular bottom surface")

    wire_data = []
    for wire in bottom_face.Wires():
        wbb = wire.BoundingBox()
        plan_area = (wbb.xmax - wbb.xmin) * (wbb.ymax - wbb.ymin)
        wire_data.append((plan_area, wbb))
    wire_data.sort(key=lambda item: item[0], reverse=True)

    # Largest wire is the outer bottom perimeter; the next wire bounds the
    # central underside opening.
    opening_bb = wire_data[1][1]
    opening_x = opening_bb.xmax - opening_bb.xmin
    opening_y = opening_bb.ymax - opening_bb.ymin
    opening_cx = 0.5 * (opening_bb.xmin + opening_bb.xmax)
    opening_cy = 0.5 * (opening_bb.ymin + opening_bb.ymax)

    # Build the 0.5 mm thick flange downward from the flat bottom surface.
    outer_plate = (
        cq.Workplane("XY")
        .workplane(offset=z_bottom - flange_thickness)
        .center(center_x, center_y)
        .rect(outer_x, outer_y)
        .extrude(flange_thickness)
    )

    opening_tool = (
        cq.Workplane("XY")
        .workplane(offset=z_bottom - flange_thickness - 0.05)
        .center(opening_cx, opening_cy)
        .rect(opening_x, opening_y)
        .extrude(flange_thickness + 0.10)
    )
    flange = outer_plate.cut(opening_tool)

    # Interpret the 0.6 mm spacing as center-to-edge spacing. Place one
    # diameter-0.5 mm through-hole near each flange corner.
    hole_diameter = 0.5
    edge_offset = 0.6
    hole_x = outer_x / 2.0 - edge_offset
    hole_y = outer_y / 2.0 - edge_offset
    hole_points = [
        (center_x - hole_x, center_y - hole_y),
        (center_x + hole_x, center_y - hole_y),
        (center_x + hole_x, center_y + hole_y),
        (center_x - hole_x, center_y + hole_y),
    ]

    flange = (
        flange.faces("<Z")
        .workplane()
        .pushPoints(hole_points)
        .hole(hole_diameter, flange_thickness)
    )

    base = cq.Workplane("XY").newObject([shape])
    result = base.union(flange)

    result_shape = result.val()
    result_bb = result_shape.BoundingBox()
    print(f"Result valid: {result_shape.isValid()}")
    print(f"Result solids: {len(result_shape.Solids())}")
    print(
        f"Result bbox: ({result_bb.xmin:.6f}, {result_bb.xmax:.6f}); "
        f"({result_bb.ymin:.6f}, {result_bb.ymax:.6f}); "
        f"({result_bb.zmin:.6f}, {result_bb.zmax:.6f})"
    )
    print(
        f"Flange: thickness={flange_thickness:.3f}, outward width={flange_width:.3f}, "
        f"outer size=({outer_x:.3f}, {outer_y:.3f}), "
        f"opening=({opening_x:.3f}, {opening_y:.3f})"
    )
    print(f"Hole centers: {hole_points}; diameter={hole_diameter:.3f}")

    return result
