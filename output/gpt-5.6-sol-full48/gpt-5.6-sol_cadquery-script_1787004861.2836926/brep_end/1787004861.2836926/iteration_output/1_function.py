def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    base_shape = imported.val()

    bbox = base_shape.BoundingBox()
    cx = (bbox.xmin + bbox.xmax) * 0.5

    body_length = bbox.zmax - bbox.zmin
    switch_x = cx
    switch_z = bbox.zmin + 0.36 * body_length
    bottom_y = bbox.ymin

    slot_length = 18.0
    slot_width = 5.0
    travel = 8.0
    pad_length = 28.0
    pad_width = 10.0
    pad_height = 2.0
    current_offset = -travel * 0.5

    slot_cutter = (
        cq.Workplane("XZ", origin=(0, bottom_y, 0))
        .center(switch_x, switch_z)
        .slot2D(slot_length, slot_width, 90)
        .extrude(12.0, both=True)
    )
    modified_housing = imported.cut(slot_cutter)

    pocket = (
        cq.Workplane("XZ", origin=(0, bottom_y + 2.2, 0))
        .center(switch_x, switch_z)
        .slot2D(slot_length + 4.0, slot_width + 4.0, 90)
        .extrude(2.4, both=True)
    )
    modified_housing = modified_housing.cut(pocket)

    slider_z = switch_z + current_offset

    pad = (
        cq.Workplane("XZ", origin=(0, bottom_y - 0.10, 0))
        .center(switch_x, slider_z)
        .slot2D(pad_length, pad_width, 90)
        .extrude(pad_height)
    )
    try:
        pad = pad.edges().fillet(0.65)
    except Exception as exc:
        print("Pad edge fillet skipped:", exc)

    neck = (
        cq.Workplane("XZ", origin=(0, bottom_y + 1.8, 0))
        .center(switch_x, slider_z)
        .slot2D(5.0, 3.2, 90)
        .extrude(3.8, both=True)
    )

    carrier = (
        cq.Workplane("XZ", origin=(0, bottom_y + 3.1, 0))
        .center(switch_x, slider_z)
        .slot2D(10.0, 7.2, 90)
        .extrude(1.2, both=True)
    )

    slider = pad.union(neck).union(carrier)

    result = cq.Assembly(name="enclosure_with_bottom_slide_switch")
    result.add(
        modified_housing,
        name="modified_existing_model",
        color=cq.Color(0.32, 0.66, 0.82)
    )
    result.add(
        slider,
        name="S04_bottom_ON_OFF_slider_OFF_position",
        color=cq.Color(0.92, 0.42, 0.10)
    )

    print("Operation finished: bottom sliding ON/OFF switch added.")
    print("Slider travel axis is parallel to global Z and is shown at the OFF endpoint.")
    return result