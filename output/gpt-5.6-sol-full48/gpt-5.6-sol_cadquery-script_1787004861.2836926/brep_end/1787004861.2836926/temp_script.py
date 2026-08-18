def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    base_shape = imported.val()

    bbox = base_shape.BoundingBox()
    cx = (bbox.xmin + bbox.xmax) * 0.5
    cy = (bbox.ymin + bbox.ymax) * 0.5
    cz = (bbox.zmin + bbox.zmax) * 0.5

    print("Imported model valid:", base_shape.isValid())
    print("Bounding box: x=(%.3f, %.3f), y=(%.3f, %.3f), z=(%.3f, %.3f)" %
          (bbox.xmin, bbox.xmax, bbox.ymin, bbox.ymax, bbox.zmin, bbox.zmax))
    print("Bounding-box center: (%.3f, %.3f, %.3f)" % (cx, cy, cz))
    print("Solid count:", len(base_shape.Solids()))
    print("Face count:", len(base_shape.Faces()))

    # Report the faces nearest the bottom for refinement after the first render.
    face_data = []
    for i, face in enumerate(base_shape.Faces()):
        fb = face.BoundingBox()
        fc = face.Center()
        face_data.append((fc.y, i, fc.x, fc.z, fb.xlen, fb.ylen, fb.zlen))
    for item in sorted(face_data)[:8]:
        print("Bottom candidate face %d: center=(%.3f, %.3f, %.3f), size=(%.3f, %.3f, %.3f)" %
              (item[1], item[2], item[0], item[3], item[4], item[5], item[6]))

    # The planning data establishes Y as the shallow vertical direction and Z as
    # the enclosure longitudinal direction. Place the switch on the broad -Y base.
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
    neck_length = 5.0
    neck_width = 3.2
    current_offset = -travel * 0.5  # Displayed in the OFF endpoint position.

    # Capsule opening, normal to a datum plane parallel to XZ. The symmetric
    # extrusion reliably passes through the subtly curved lower shell only.
    slot_cutter = (
        cq.Workplane("XZ", origin=(0, bottom_y, 0))
        .center(switch_x, switch_z)
        .slot2D(slot_length, slot_width, 90)
        .extrude(12.0, both=True)
    )
    modified_housing = imported.cut(slot_cutter)

    # Add a shallow internal clearance pocket for the actuator carrier. It is
    # intentionally wider than the neck but remains local to the underside.
    pocket = (
        cq.Workplane("XZ", origin=(0, bottom_y + 2.2, 0))
        .center(switch_x, switch_z)
        .slot2D(slot_length + 4.0, slot_width + 4.0, 90)
        .extrude(2.4, both=True)
    )
    modified_housing = modified_housing.cut(pocket)

    slider_z = switch_z + current_offset

    # External rounded finger pad. On the XZ plane, positive extrusion points
    # toward -Y, i.e. outward from the enclosure bottom.
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

    # Narrow actuator neck passing through the housing slot.
    neck = (
        cq.Workplane("XZ", origin=(0, bottom_y + 1.8, 0))
        .center(switch_x, slider_z)
        .slot2D(neck_length, neck_width, 90)
        .extrude(3.8, both=True)
    )

    # Internal carrier couples the external pad to a commercial two-position
    # slide-switch actuator while providing broad guide surfaces beneath the shell.
    carrier = (
        cq.Workplane("XZ", origin=(0, bottom_y + 3.1, 0))
        .center(switch_x, slider_z)
        .slot2D(10.0, 7.2, 90)
        .extrude(1.2, both=True)
    )

    slider = pad.union(neck).union(carrier)

    result = cq.Assembly(name="enclosure_with_bottom_slide_switch")
    result.add(modified_housing, name="modified_existing_model",
               color=cq.Color(0.32, 0.66, 0.82))
    result.add(slider, name="S04_bottom_ON_OFF_slider_OFF_position",
               color=cq.Color(0.92, 0.42, 0.10))

    print("Switch center: x=%.3f, y=%.3f, z=%.3f" %
          (switch_x, bottom_y, switch_z))
    print("Created capsule slot %.1f x %.1f mm and separate %.1f x %.1f mm slider." %
          (slot_length, slot_width, pad_length, pad_width))
    print("Slider travel axis is parallel to global Z; modeled at OFF endpoint.")
    return result