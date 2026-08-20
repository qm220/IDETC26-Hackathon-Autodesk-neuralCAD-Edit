def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    print(f"Loaded STEP: {input_file}")
    print(f"Valid: {shape.isValid()}, solids: {len(shape.Solids())}, faces: {len(shape.Faces())}")
    model_bb = shape.BoundingBox()
    print(
        f"Model bbox: x=({model_bb.xmin:.6f},{model_bb.xmax:.6f}), "
        f"y=({model_bb.ymin:.6f},{model_bb.ymax:.6f}), "
        f"z=({model_bb.zmin:.6f},{model_bb.zmax:.6f})"
    )

    # Inspect and print the actual imported face geometry before editing.
    faces = shape.Faces()
    for index, face in enumerate(faces):
        bb = face.BoundingBox()
        center = face.Center()
        try:
            geometry_type = face.geomType()
        except Exception:
            geometry_type = "UNKNOWN"
        print(
            f"FACE {index}: type={geometry_type}, area={face.Area():.6f}, "
            f"center=({center.x:.6f},{center.y:.6f},{center.z:.6f}), "
            f"bbox=x({bb.xmin:.6f},{bb.xmax:.6f}) "
            f"y({bb.ymin:.6f},{bb.ymax:.6f}) "
            f"z({bb.zmin:.6f},{bb.zmax:.6f}), wires={len(face.Wires())}"
        )

    # Bind F005 / planned FACE 11 to geometry rather than relying solely on
    # the imported face ordering: it is the lowest horizontal planar face
    # having both an outer wire and the pocket-opening inner wire.
    z_tolerance = 1.0e-6
    bottom_candidates = []
    for index, face in enumerate(faces):
        bb = face.BoundingBox()
        try:
            is_plane = face.geomType() == "PLANE"
        except Exception:
            is_plane = False
        if (
            is_plane
            and abs(bb.zmin - model_bb.zmin) <= z_tolerance
            and abs(bb.zmax - model_bb.zmin) <= z_tolerance
            and len(face.Wires()) >= 2
        ):
            bottom_candidates.append((index, face))

    if not bottom_candidates:
        raise ValueError("Could not localize the two-wire planar bottom mounting face F005")

    bottom_index, bottom_face = max(bottom_candidates, key=lambda item: item[1].Area())
    bottom_z = bottom_face.BoundingBox().zmin
    print(f"Bound F005 bottom mounting surface to actual FACE {bottom_index} at z={bottom_z:.6f}")

    # Inspect its wires. The largest XY-bounding wire is the existing outer
    # footprint and the other wire is the open underside pocket boundary.
    wire_data = []
    for wire_index, wire in enumerate(bottom_face.Wires()):
        bb = wire.BoundingBox()
        xy_box_area = (bb.xmax - bb.xmin) * (bb.ymax - bb.ymin)
        wire_data.append((xy_box_area, wire_index, bb))
        print(
            f"  bottom wire {wire_index}: x=({bb.xmin:.6f},{bb.xmax:.6f}), "
            f"y=({bb.ymin:.6f},{bb.ymax:.6f}), bbox_area={xy_box_area:.6f}"
        )

    wire_data.sort(key=lambda item: item[0], reverse=True)
    outer_bb = wire_data[0][2]
    inner_bb = wire_data[-1][2]

    flange_width = 2.0
    flange_thickness = 0.5
    hole_diameter = 0.5
    center_edge_spacing = 0.6

    outer_xmin = outer_bb.xmin - flange_width
    outer_xmax = outer_bb.xmax + flange_width
    outer_ymin = outer_bb.ymin - flange_width
    outer_ymax = outer_bb.ymax + flange_width
    outer_size_x = outer_xmax - outer_xmin
    outer_size_y = outer_ymax - outer_ymin
    outer_center_x = 0.5 * (outer_xmin + outer_xmax)
    outer_center_y = 0.5 * (outer_ymin + outer_ymax)

    # Preserve the inner wire of FACE 11 as the through-opening, nominally
    # x=(-0.8,0.8), y=(-2.8,2.8).
    inner_size_x = inner_bb.xmax - inner_bb.xmin
    inner_size_y = inner_bb.ymax - inner_bb.ymin
    inner_center_x = 0.5 * (inner_bb.xmin + inner_bb.xmax)
    inner_center_y = 0.5 * (inner_bb.ymin + inner_bb.ymax)

    print(
        f"Flange outer limits: x=({outer_xmin:.6f},{outer_xmax:.6f}), "
        f"y=({outer_ymin:.6f},{outer_ymax:.6f}), "
        f"z=({bottom_z-flange_thickness:.6f},{bottom_z:.6f})"
    )
    print(
        f"Preserved central opening: x=({inner_bb.xmin:.6f},{inner_bb.xmax:.6f}), "
        f"y=({inner_bb.ymin:.6f},{inner_bb.ymax:.6f})"
    )

    flange_plane = cq.Workplane("XY", origin=(0.0, 0.0, bottom_z))
    flange = (
        flange_plane
        .center(outer_center_x, outer_center_y)
        .rect(outer_size_x, outer_size_y)
        .center(inner_center_x - outer_center_x, inner_center_y - outer_center_y)
        .rect(inner_size_x, inner_size_y)
        .extrude(-flange_thickness)
    )

    # Conventional interpretation: each hole center is 0.6 mm inward from
    # both adjacent outer flange edges.
    hole_points = [
        (outer_xmin + center_edge_spacing, outer_ymin + center_edge_spacing),
        (outer_xmax - center_edge_spacing, outer_ymin + center_edge_spacing),
        (outer_xmin + center_edge_spacing, outer_ymax - center_edge_spacing),
        (outer_xmax - center_edge_spacing, outer_ymax - center_edge_spacing),
    ]
    print(f"Hole centers: {hole_points}; diameter={hole_diameter:.6f}")

    hole_tools = (
        cq.Workplane("XY", origin=(0.0, 0.0, bottom_z))
        .pushPoints(hole_points)
        .circle(hole_diameter / 2.0)
        .extrude(-flange_thickness)
    )
    drilled_flange = flange.cut(hole_tools)

    # Fuse through the existing planar mounting rim. The central pocket remains
    # open because its actual inner boundary was retained in the flange profile.
    result = model.union(drilled_flange).clean()
    result_shape = result.val()
    result_bb = result_shape.BoundingBox()
    print(
        f"Result valid: {result_shape.isValid()}, solids: {len(result_shape.Solids())}, "
        f"volume: {result_shape.Volume():.6f}, faces: {len(result_shape.Faces())}"
    )
    print(
        f"Result bbox: x=({result_bb.xmin:.6f},{result_bb.xmax:.6f}), "
        f"y=({result_bb.ymin:.6f},{result_bb.ymax:.6f}), "
        f"z=({result_bb.zmin:.6f},{result_bb.zmax:.6f})"
    )

    if len(result_shape.Solids()) != 1:
        raise ValueError("Edited model did not produce one connected solid")
    if not result_shape.isValid():
        raise ValueError("Edited model is not a valid B-rep solid")

    return result