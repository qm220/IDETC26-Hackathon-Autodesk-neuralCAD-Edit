def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported
    solids = list(root.Solids())
    if not solids:
        raise ValueError("The input STEP file contains no solids")

    housing_index = max(range(len(solids)), key=lambda i: solids[i].Volume())
    housing = solids[housing_index]
    preserved = [s for i, s in enumerate(solids) if i != housing_index]

    bb = housing.BoundingBox()
    faces = list(housing.Faces())
    bottom_face = min(faces, key=lambda f: f.Center().y)
    bottom_center = bottom_face.Center()

    x_mid = bottom_center.x
    surface_y = bottom_center.y
    length_z = bb.zmax - bb.zmin
    switch_z = bottom_center.z - 0.10 * length_z
    switch_z = max(bb.zmin + 12.0, min(bb.zmax - 12.0, switch_z))

    print("Input solids:", len(solids))
    print("Housing bbox:", bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax)
    print("Selected bottom face center:", bottom_center.x, bottom_center.y, bottom_center.z)
    print("Bottom switch center:", x_mid, surface_y, switch_z)

    def rounded_y_prism(width_x, length_z, radius, y_start, depth_y, cx, cz):
        if width_x <= 2.0 * radius or length_z <= 2.0 * radius:
            raise ValueError("Rounded prism dimensions must exceed twice the radius")

        horizontal = cq.Solid.makeBox(
            width_x, depth_y, length_z - 2.0 * radius,
            cq.Vector(cx - width_x / 2.0, y_start, cz - length_z / 2.0 + radius)
        )
        vertical = cq.Solid.makeBox(
            width_x - 2.0 * radius, depth_y, length_z,
            cq.Vector(cx - width_x / 2.0 + radius, y_start, cz - length_z / 2.0)
        )
        result = horizontal.fuse(vertical)

        for dx in (-width_x / 2.0 + radius, width_x / 2.0 - radius):
            for dz in (-length_z / 2.0 + radius, length_z / 2.0 - radius):
                corner = cq.Solid.makeCylinder(
                    radius, depth_y,
                    cq.Vector(cx + dx, y_start, cz + dz),
                    cq.Vector(0, 1, 0)
                )
                result = result.fuse(corner)
        return result

    def obround_y_prism(overall_z, width_x, y_start, depth_y, cx, cz):
        radius = width_x / 2.0
        straight_z = overall_z - width_x
        if straight_z <= 0:
            raise ValueError("Obround length must exceed its width")

        result = cq.Solid.makeBox(
            width_x, depth_y, straight_z,
            cq.Vector(cx - radius, y_start, cz - straight_z / 2.0)
        )
        for dz in (-straight_z / 2.0, straight_z / 2.0):
            end = cq.Solid.makeCylinder(
                radius, depth_y,
                cq.Vector(cx, y_start, cz + dz),
                cq.Vector(0, 1, 0)
            )
            result = result.fuse(end)
        return result

    # Localized 10 x 18 mm rounded recess in the underside.
    recess_depth = 1.2
    recess = rounded_y_prism(
        10.0, 18.0, 2.0,
        surface_y - 0.15, recess_depth + 0.35,
        x_mid, switch_z
    )
    edited_housing = housing.cut(recess)

    # Internal clearance for the miniature switch body, leaving material around the recess.
    cavity = cq.Solid.makeBox(
        8.0, 5.8, 15.0,
        cq.Vector(x_mid - 4.0, surface_y + 2.0, switch_z - 7.5)
    )
    edited_housing = edited_housing.cut(cavity)

    # Through obround slot: 8 mm along Z, 3 mm across X.
    slot = obround_y_prism(
        8.0, 3.0,
        surface_y - 0.25, 8.4,
        x_mid, switch_z
    )
    edited_housing = edited_housing.cut(slot)

    # Engraved O and I labels at the two longitudinal endpoints.
    floor_y = surface_y + recess_depth
    mark_depth = 0.28

    o_x = x_mid - 3.1
    o_z = switch_z - 6.0
    outer_o = cq.Solid.makeCylinder(
        1.0, mark_depth,
        cq.Vector(o_x, floor_y - 0.03, o_z), cq.Vector(0, 1, 0)
    )
    inner_o = cq.Solid.makeCylinder(
        0.55, mark_depth + 0.08,
        cq.Vector(o_x, floor_y - 0.07, o_z), cq.Vector(0, 1, 0)
    )
    edited_housing = edited_housing.cut(outer_o.cut(inner_o))

    i_x = x_mid + 3.1
    i_z = switch_z + 6.0
    i_mark = cq.Solid.makeBox(
        0.55, mark_depth, 2.1,
        cq.Vector(i_x - 0.275, floor_y - 0.03, i_z - 1.05)
    )
    edited_housing = edited_housing.cut(i_mark)

    # Separate miniature switch body retained within the internal clearance pocket.
    switch_body = cq.Solid.makeBox(
        7.0, 3.4, 14.0,
        cq.Vector(x_mid - 3.5, surface_y + 3.8, switch_z - 7.0)
    )

    # Show the actuator at the positive-Z ON endpoint of a 4 mm travel range.
    slider_z = switch_z + 2.0
    pad = rounded_y_prism(
        5.2, 7.0, 2.2,
        surface_y - 0.85, 2.20,
        x_mid, slider_z
    )

    stem = cq.Solid.makeBox(
        2.3, 2.45, 2.8,
        cq.Vector(x_mid - 1.15, surface_y + 0.70, slider_z - 1.4)
    )
    flange = cq.Solid.makeBox(
        4.3, 0.65, 4.2,
        cq.Vector(x_mid - 2.15, surface_y + 2.85, slider_z - 2.1)
    )
    actuator = pad.fuse(stem).fuse(flange)

    if not edited_housing.isValid():
        raise ValueError("Localized switch cuts produced an invalid housing")
    if not switch_body.isValid() or not actuator.isValid():
        raise ValueError("Switch component construction failed")

    result = cq.Assembly(name="mouse_with_bottom_power_switch")
    result.add(
        edited_housing,
        name="edited_main_housing",
        color=cq.Color(0.18, 0.20, 0.43, 0.92)
    )

    for i, solid in enumerate(preserved):
        color = cq.Color(0.12, 0.48, 0.16, 1.0) if i == 0 else cq.Color(0.55, 0.55, 0.58, 1.0)
        result.add(solid, name="preserved_original_%d" % i, color=color)

    result.add(
        switch_body,
        name="bottom_power_switch_body",
        color=cq.Color(0.10, 0.10, 0.12, 1.0)
    )
    result.add(
        actuator,
        name="power_slider_ON",
        color=cq.Color(0.92, 0.36, 0.08, 1.0)
    )

    print("Added recessed underside power switch with a 4 mm longitudinal travel range")
    print("Displayed slider state: ON (+Z endpoint)")
    print("Edited housing valid:", edited_housing.isValid())
    return result