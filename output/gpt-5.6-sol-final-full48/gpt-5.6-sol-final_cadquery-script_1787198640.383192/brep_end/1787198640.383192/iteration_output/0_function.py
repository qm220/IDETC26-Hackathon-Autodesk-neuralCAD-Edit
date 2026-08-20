def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported
    solids = list(root.Solids())
    if not solids:
        raise ValueError("The input STEP file contains no solids")

    # The housing is the largest imported solid; all other imported solids are preserved.
    housing_index = max(range(len(solids)), key=lambda i: solids[i].Volume())
    housing = solids[housing_index]
    preserved = [s for i, s in enumerate(solids) if i != housing_index]

    bb = housing.BoundingBox()
    x_mid = 0.5 * (bb.xmin + bb.xmax)
    z_mid = 0.5 * (bb.zmin + bb.zmax)
    length_z = bb.zmax - bb.zmin
    y_bottom = bb.ymin

    # Rear-central location, moved toward the longitudinal center if required by the envelope.
    switch_z = z_mid - 0.15 * length_z
    switch_z = max(bb.zmin + 12.0, min(bb.zmax - 12.0, switch_z))

    print("Input solids:", len(solids))
    print("Housing bbox:", bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax)
    print("Bottom switch center:", x_mid, y_bottom, switch_z)

    def underside_rounded_prism(width_x, length_z, radius, y_start, depth_y, cx, cz):
        # XZ plane has a -Y normal, so a negative extrusion proceeds inward in +Y.
        plane = cq.Plane(origin=(cx, y_start, cz), xDir=(1, 0, 0), normal=(0, -1, 0))
        return (cq.Workplane(plane)
                .roundedRect(width_x, length_z, radius)
                .extrude(-depth_y)
                .val())

    # Shallow 18 x 10 mm underside recess, with its long direction along Z.
    recess_depth = 1.2
    recess = underside_rounded_prism(
        10.0, 18.0, 2.0, y_bottom - 0.05, recess_depth + 0.08, x_mid, switch_z
    )
    edited_housing = housing.cut(recess)

    # Internal clearance for a miniature switch body. It remains localized below the switch.
    cavity_y0 = y_bottom + 2.15
    cavity = cq.Solid.makeBox(
        8.0, 4.8, 15.0,
        cq.Vector(x_mid - 4.0, cavity_y0, switch_z - 7.5)
    )
    edited_housing = edited_housing.cut(cavity)

    # Through obround travel opening, 8 x 3 mm, parallel to Z.
    slot_plane = cq.Plane(
        origin=(x_mid, y_bottom - 0.10, switch_z),
        xDir=(1, 0, 0), normal=(0, -1, 0)
    )
    slot = (cq.Workplane(slot_plane)
            .slot2D(8.0, 3.0, 90.0)
            .extrude(-7.5)
            .val())
    edited_housing = edited_housing.cut(slot)

    # Engraved standard O and I endpoint markings in the recessed floor.
    floor_y = y_bottom + recess_depth
    mark_depth = 0.22
    o_x = x_mid - 3.35
    o_z = switch_z - 4.8
    outer_o = cq.Solid.makeCylinder(
        1.05, mark_depth + 0.05,
        cq.Vector(o_x, floor_y - 0.02, o_z), cq.Vector(0, 1, 0)
    )
    inner_o = cq.Solid.makeCylinder(
        0.58, mark_depth + 0.10,
        cq.Vector(o_x, floor_y - 0.04, o_z), cq.Vector(0, 1, 0)
    )
    o_mark = outer_o.cut(inner_o)
    edited_housing = edited_housing.cut(o_mark)

    i_x = x_mid + 3.35
    i_z = switch_z + 4.8
    i_mark = cq.Solid.makeBox(
        0.55, mark_depth + 0.05, 2.2,
        cq.Vector(i_x - 0.275, floor_y - 0.02, i_z - 1.1)
    )
    edited_housing = edited_housing.cut(i_mark)

    # Separate internal switch body, fitted inside the clearance cavity.
    switch_body = cq.Solid.makeBox(
        7.0, 3.7, 14.0,
        cq.Vector(x_mid - 3.5, y_bottom + 2.65, switch_z - 7.0)
    )

    # Slider is shown at the positive-Z (ON / I) endpoint of its 4 mm stroke.
    slider_z = switch_z + 2.0

    # Exterior pill-shaped finger pad. It rises slightly below the original underside.
    pad = underside_rounded_prism(
        5.0, 7.0, 2.35, y_bottom - 0.85, 2.02, x_mid, slider_z
    )

    # Narrow stem passes through the obround slot with lateral running clearance.
    stem = cq.Solid.makeBox(
        2.4, 2.2, 2.8,
        cq.Vector(x_mid - 1.2, y_bottom + 0.75, slider_z - 1.4)
    )

    # Captive flange is wider than the slot but remains clear of the switch cavity walls.
    flange = cq.Solid.makeBox(
        4.2, 0.65, 4.0,
        cq.Vector(x_mid - 2.1, y_bottom + 2.35, slider_z - 2.0)
    )
    actuator = pad.fuse(stem).fuse(flange)

    if not edited_housing.isValid():
        raise ValueError("Localized switch cuts produced an invalid housing")
    if not actuator.isValid() or not switch_body.isValid():
        raise ValueError("Switch component construction failed")

    result = cq.Assembly(name="mouse_with_bottom_power_switch")
    result.add(edited_housing, name="edited_main_housing", color=cq.Color(0.18, 0.20, 0.43, 0.92))

    for i, solid in enumerate(preserved):
        color = cq.Color(0.12, 0.48, 0.16, 1.0) if i == 0 else cq.Color(0.55, 0.55, 0.58, 1.0)
        result.add(solid, name="preserved_original_%d" % i, color=color)

    result.add(switch_body, name="bottom_power_switch_body", color=cq.Color(0.12, 0.12, 0.14, 1.0))
    result.add(actuator, name="power_slider_ON", color=cq.Color(0.92, 0.36, 0.08, 1.0))

    print("Added recessed bottom power switch with 4 mm longitudinal stroke")
    print("Slider configuration: ON (+Z endpoint)")
    print("Edited housing valid:", edited_housing.isValid())
    return result