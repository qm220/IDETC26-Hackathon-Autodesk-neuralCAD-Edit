def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    model = imported.val() if hasattr(imported, "val") else imported

    bbox = model.BoundingBox()
    print(f"Loaded model valid: {model.isValid()}")
    print(f"Model solids: {len(model.Solids())}, faces: {len(model.Faces())}")
    print(f"Model bbox: X[{bbox.xmin:.3f}, {bbox.xmax:.3f}] Y[{bbox.ymin:.3f}, {bbox.ymax:.3f}] Z[{bbox.zmin:.3f}, {bbox.zmax:.3f}]")

    # Inspect and bind the planned FACE 9 bottom/support surface to the actual STEP geometry.
    faces = model.Faces()
    for index, face in enumerate(faces):
        center = face.Center()
        fb = face.BoundingBox()
        print(
            f"FACE {index}: geom={face.geomType()}, "
            f"center=({center.x:.3f},{center.y:.3f},{center.z:.3f}), "
            f"bbox=X[{fb.xmin:.3f},{fb.xmax:.3f}] "
            f"Y[{fb.ymin:.3f},{fb.ymax:.3f}] "
            f"Z[{fb.zmin:.3f},{fb.zmax:.3f}]"
        )

    bottom_face = faces[9] if len(faces) > 9 else min(faces, key=lambda f: f.Center().y)
    bottom_center = bottom_face.Center()
    print(
        f"Grounded switch placement to FACE 9: "
        f"center=({bottom_center.x:.3f},{bottom_center.y:.3f},{bottom_center.z:.3f}), "
        f"geom={bottom_face.geomType()}"
    )

    dx = bbox.xmax - bbox.xmin
    dz = bbox.zmax - bbox.zmin
    switch_width = max(10.0, min(16.0, dx * 0.18))
    switch_length = max(20.0, min(30.0, dz * 0.25))
    plate_thickness = 2.2

    # Center the control laterally and place it slightly toward the back of the bottom.
    x_pos = max(bbox.xmin + switch_width, min(bbox.xmax - switch_width, bottom_center.x))
    z_pos = (bbox.zmin + bbox.zmax) * 0.5 - dz * 0.15
    z_pos = max(bbox.zmin + switch_length * 0.6, min(bbox.zmax - switch_length * 0.6, z_pos))
    y_surface = bbox.ymin

    # A shallow switch bezel contacts the housing at its bottom-most extent.
    bezel = (
        cq.Workplane("XZ")
        .box(switch_width, switch_length, plate_thickness)
        .edges()
        .fillet(0.8)
        .translate((x_pos, y_surface - plate_thickness * 0.5, z_pos))
    )

    # Raised parallel guide rails make the allowed sliding direction explicit.
    rail_width = 1.25
    rail_length = switch_length * 0.68
    rail_thickness = 1.0
    rail_offset = switch_width * 0.34
    left_rail = (
        cq.Workplane("XZ")
        .box(rail_width, rail_length, rail_thickness)
        .edges()
        .fillet(0.35)
        .translate((x_pos - rail_offset, y_surface - plate_thickness - rail_thickness * 0.5, z_pos))
    )
    right_rail = (
        cq.Workplane("XZ")
        .box(rail_width, rail_length, rail_thickness)
        .edges()
        .fillet(0.35)
        .translate((x_pos + rail_offset, y_surface - plate_thickness - rail_thickness * 0.5, z_pos))
    )

    # The movable actuator is shown in one of its two stable positions.
    knob_width = switch_width * 0.58
    knob_length = switch_length * 0.28
    knob_height = 3.2
    travel = switch_length * 0.24
    knob_z = z_pos + travel * 0.5
    slider = (
        cq.Workplane("XZ")
        .box(knob_width, knob_length, knob_height)
        .edges()
        .fillet(1.0)
        .translate((x_pos, y_surface - plate_thickness - knob_height * 0.5, knob_z))
    )

    # Three tactile ribs provide grip for convenient finger operation.
    ribs = []
    for offset in (-knob_length * 0.22, 0.0, knob_length * 0.22):
        rib = (
            cq.Workplane("XZ")
            .box(knob_width * 0.72, 0.7, 0.65)
            .edges()
            .fillet(0.2)
            .translate((x_pos, y_surface - plate_thickness - knob_height - 0.325, knob_z + offset))
        )
        ribs.append(rib)

    # Two end-state markers visually identify the OFF and ON detent positions.
    marker_width = switch_width * 0.42
    marker_length = 1.0
    marker_height = 0.65
    off_marker = (
        cq.Workplane("XZ")
        .box(marker_width, marker_length, marker_height)
        .edges()
        .fillet(0.2)
        .translate((x_pos, y_surface - plate_thickness - marker_height * 0.5, z_pos - switch_length * 0.39))
    )
    on_marker = (
        cq.Workplane("XZ")
        .box(marker_width, marker_length, marker_height)
        .edges()
        .fillet(0.2)
        .translate((x_pos, y_surface - plate_thickness - marker_height * 0.5, z_pos + switch_length * 0.39))
    )

    assembly = cq.Assembly(name="mouse_with_bottom_sliding_switch")
    assembly.add(model, name="original_mouse_housing_and_wheel", color=cq.Color(0.72, 0.72, 0.75))
    assembly.add(bezel, name="sliding_switch_bezel", color=cq.Color(0.12, 0.12, 0.14))
    assembly.add(left_rail, name="switch_left_guide", color=cq.Color(0.22, 0.22, 0.24))
    assembly.add(right_rail, name="switch_right_guide", color=cq.Color(0.22, 0.22, 0.24))
    assembly.add(slider, name="on_off_sliding_actuator", color=cq.Color(0.85, 0.22, 0.12))
    for index, rib in enumerate(ribs):
        assembly.add(rib, name=f"actuator_grip_rib_{index + 1}", color=cq.Color(0.35, 0.05, 0.03))
    assembly.add(off_marker, name="off_state_marker", color=cq.Color(0.85, 0.85, 0.85))
    assembly.add(on_marker, name="on_state_marker", color=cq.Color(0.25, 0.85, 0.35))

    print(
        f"Added bottom sliding switch at ({x_pos:.3f}, {y_surface:.3f}, {z_pos:.3f}); "
        f"bezel size={switch_width:.2f} x {switch_length:.2f} mm, travel={travel:.2f} mm"
    )
    return assembly