def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported

    # Inspect and bind the planned FACE 9 target to the imported geometry.
    all_faces = root.Faces()
    print("Imported face count:", len(all_faces))
    for i, face in enumerate(all_faces):
        bb = face.BoundingBox()
        c = face.Center()
        try:
            geom_type = face.geomType()
        except Exception:
            geom_type = "UNKNOWN"
        print(
            "FACE %d type=%s area=%.3f center=(%.3f, %.3f, %.3f) "
            "bbox=(%.3f, %.3f, %.3f)-(%.3f, %.3f, %.3f)" % (
                i, geom_type, face.Area(), c.x, c.y, c.z,
                bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax
            )
        )

    root_bb = root.BoundingBox()
    bottom_candidates = []
    for i, face in enumerate(all_faces):
        bb = face.BoundingBox()
        # Broad faces close to the global -Y side are candidates for F002.
        if bb.ymax <= root_bb.ymin + 4.0:
            bottom_candidates.append((face.Area(), i, face))
    if not bottom_candidates:
        raise ValueError("Could not localize the lower housing face")
    bottom_candidates.sort(key=lambda item: item[0], reverse=True)
    _, bottom_index, bottom_face = bottom_candidates[0]
    bottom_bb = bottom_face.BoundingBox()
    print("Bound semantic bottom F002 to imported FACE", bottom_index)
    print("Bottom face area=%.3f, Y range=(%.3f, %.3f)" % (
        bottom_face.Area(), bottom_bb.ymin, bottom_bb.ymax
    ))

    solids = list(root.Solids())
    if len(solids) < 2:
        raise ValueError("Expected the housing and separate scroll wheel solids")
    solids.sort(key=lambda s: s.Volume(), reverse=True)
    housing = solids[0]
    retained_solids = solids[1:]
    print("Solid count:", len(solids))
    for i, solid in enumerate(solids):
        bb = solid.BoundingBox()
        print("SOLID %d volume=%.3f bbox=(%.3f, %.3f, %.3f)-(%.3f, %.3f, %.3f)" % (
            i, solid.Volume(), bb.xmin, bb.ymin, bb.zmin,
            bb.xmax, bb.ymax, bb.zmax
        ))

    # Named compact two-position switch parameters, in millimetres.
    switch_x = 27.25
    switch_z = 18.0
    aperture_length = 14.0
    aperture_width = 4.0
    slider_travel = 6.0
    recess_length = 21.0
    recess_width = 11.0
    recess_depth = 1.35
    actuator_projection = 1.8
    running_clearance = 0.35
    edge_radius = 1.5
    minimum_wall_land = 2.0
    print("Switch parameters:", {
        "aperture_length": aperture_length,
        "aperture_width": aperture_width,
        "slider_travel": slider_travel,
        "recess_depth": recess_depth,
        "actuator_projection": actuator_projection,
        "running_clearance": running_clearance,
        "edge_radius": edge_radius,
        "minimum_wall_land": minimum_wall_land
    })

    # The selected center is on the broad underside and is well forward of the
    # wheel pocket, whose grounded Z interval starts near 43.5 mm.
    if switch_z + recess_length / 2.0 >= 40.0:
        raise ValueError("Switch recess is too close to the wheel pocket")

    def rounded_rect_prism(cx, cz, width, length, radius, y0, height):
        """Axis-aligned rounded rectangle in XZ, extruded along +Y."""
        radius = min(radius, width / 2.0 - 0.01, length / 2.0 - 0.01)
        a = cq.Solid.makeBox(
            width - 2.0 * radius, height, length,
            cq.Vector(cx - width / 2.0 + radius, y0, cz - length / 2.0)
        )
        b = cq.Solid.makeBox(
            width, height, length - 2.0 * radius,
            cq.Vector(cx - width / 2.0, y0, cz - length / 2.0 + radius)
        )
        result = a.fuse(b)
        for x in (cx - width / 2.0 + radius, cx + width / 2.0 - radius):
            for z in (cz - length / 2.0 + radius, cz + length / 2.0 - radius):
                corner = cq.Solid.makeCylinder(
                    radius, height, cq.Vector(x, y0, z), cq.Vector(0, 1, 0)
                )
                result = result.fuse(corner)
        return result

    # FACE 9 varies only slightly in Y. Start cutters below its minimum and
    # drive them inward in +Y, matching the grounded modeling plan.
    cutter_y0 = bottom_bb.ymin - 1.0
    recess_height = (bottom_bb.ymax - cutter_y0) + recess_depth
    recess_tool = rounded_rect_prism(
        switch_x, switch_z, recess_width, recess_length, 2.0,
        cutter_y0, recess_height
    )

    # Narrow actuator slot continues through the local lower material. It is
    # kept far from the central wheel pocket and upper wheel assembly.
    slot_tool = rounded_rect_prism(
        switch_x, switch_z, aperture_width, aperture_length, edge_radius,
        cutter_y0, 8.5
    )
    edited_housing = housing.cut(recess_tool).cut(slot_tool)
    if not edited_housing.isValid():
        raise ValueError("Housing became invalid after switch cuts")

    # Separate seated bezel: a rounded frame surrounding the actuator slot.
    bezel_y0 = bottom_bb.ymin - 0.75
    bezel_height = 1.05
    bezel_outer = rounded_rect_prism(
        switch_x, switch_z, recess_width - 0.5, recess_length - 0.5, 1.8,
        bezel_y0, bezel_height
    )
    bezel_opening = rounded_rect_prism(
        switch_x, switch_z, aperture_width + 0.7,
        aperture_length + 0.7, edge_radius + running_clearance,
        bezel_y0 - 0.1, bezel_height + 0.2
    )
    bezel = bezel_outer.cut(bezel_opening)

    # Place the movable actuator at the OFF endpoint. Its permitted second
    # endpoint is +slider_travel along CAD Z.
    actuator_z = switch_z - slider_travel / 2.0
    pad_width = 7.0
    pad_length = 7.0
    pad_top_y = bezel_y0 + 0.2
    pad_y0 = pad_top_y - actuator_projection
    thumb_pad = rounded_rect_prism(
        switch_x, actuator_z, pad_width, pad_length, 1.7,
        pad_y0, actuator_projection
    )
    stem_width = aperture_width - 2.0 * running_clearance
    stem_length = 3.8
    stem = rounded_rect_prism(
        switch_x, actuator_z, stem_width, stem_length, 0.8,
        pad_top_y - 0.1, 4.7
    )
    actuator = thumb_pad.fuse(stem)

    # Simple tactile guide ribs under the thumb pad emphasize Z-direction
    # sliding without changing the actuator's single-solid construction.
    rib_width = 0.55
    rib_height = 0.28
    for dx in (-1.65, 0.0, 1.65):
        rib = cq.Solid.makeBox(
            rib_width, rib_height, 4.3,
            cq.Vector(switch_x + dx - rib_width / 2.0,
                      pad_y0 - rib_height,
                      actuator_z - 2.15)
        )
        actuator = actuator.fuse(rib)

    if not bezel.isValid() or not actuator.isValid():
        raise ValueError("Switch component construction produced invalid geometry")

    on_endpoint = actuator_z + slider_travel
    print("Actuator OFF center Z=%.3f, ON center Z=%.3f" % (
        actuator_z, on_endpoint
    ))
    print("Switch located on -Y bottom at X=%.3f, Z=%.3f" % (
        switch_x, switch_z
    ))

    result = cq.Assembly(name="mouse_with_bottom_slide_switch")
    result.add(edited_housing, name="edited_housing", color=cq.Color(0.19, 0.44, 0.75))
    for i, solid in enumerate(retained_solids):
        result.add(solid, name="retained_original_solid_%d" % i,
                   color=cq.Color(0.21, 0.66, 0.36))
    result.add(bezel, name="bottom_switch_bezel", color=cq.Color(0.12, 0.12, 0.12))
    result.add(actuator, name="movable_slide_actuator_OFF",
               color=cq.Color(0.92, 0.32, 0.12))
    return result