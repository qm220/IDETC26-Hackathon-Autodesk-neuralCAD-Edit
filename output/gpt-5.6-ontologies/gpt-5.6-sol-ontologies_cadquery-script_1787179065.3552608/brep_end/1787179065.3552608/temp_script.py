def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model
    solids = list(shape.Solids())

    if len(solids) < 20:
        raise ValueError(f"Expected at least 20 solids in the source model, found {len(solids)}")

    # SOLID 19 is the original plug. Preserve all other source geometry,
    # including the flexible cord and its original placement.
    preserved = [solid for index, solid in enumerate(solids) if index != 19]

    # Existing cord-to-plug interface and outward plug direction, determined
    # from the source plug geometry. The replacement remains at this interface.
    rear = (-152.385, 31.750, -266.704)
    axis = (-0.234, 0.0, -0.972)
    transverse = (0.972, 0.0, -0.234)

    def point_at(axial, lateral=0.0, y_offset=0.0):
        return (
            rear[0] + axis[0] * axial + transverse[0] * lateral,
            rear[1] + y_offset,
            rear[2] + axis[2] * axial + transverse[2] * lateral,
        )

    # Generate a sampled rounded-rectangle wire. This avoids roundedRect(),
    # which is unavailable in the CadQuery version used by the executor.
    def rounded_rectangle_points(width, height, radius, arc_segments=5):
        import math
        half_w = width / 2.0
        half_h = height / 2.0
        radius = min(radius, half_w, half_h)
        centers_and_ranges = [
            ((half_w - radius, -half_h + radius), -90.0, 0.0),
            ((half_w - radius, half_h - radius), 0.0, 90.0),
            ((-half_w + radius, half_h - radius), 90.0, 180.0),
            ((-half_w + radius, -half_h + radius), 180.0, 270.0),
        ]
        points = []
        for (cx, cy), start_angle, end_angle in centers_and_ranges:
            for segment in range(arc_segments + 1):
                if points and segment == 0:
                    continue
                angle = math.radians(
                    start_angle + (end_angle - start_angle) * segment / arc_segments
                )
                points.append((
                    cx + radius * math.cos(angle),
                    cy + radius * math.sin(angle),
                ))
        return points

    # CEE 7/16-inspired molded body. The small rear profile forms a realistic
    # strain-relief neck, while the broad flattened body tapers toward its pin face.
    body_plane = cq.Plane(
        origin=point_at(-2.0),
        xDir=transverse,
        normal=axis,
    )

    profile_data = [
        (8.0, 5.5, 2.0),
        (15.0, 8.0, 3.0),
        (30.0, 12.5, 5.0),
        (36.0, 14.0, 5.8),
        (33.0, 12.5, 5.0),
    ]
    profile_offsets = [4.0, 6.0, 10.0, 6.0]

    body_workplane = cq.Workplane(body_plane)
    first = profile_data[0]
    body_workplane = body_workplane.polyline(
        rounded_rectangle_points(first[0], first[1], first[2])
    ).close()

    for offset, profile in zip(profile_offsets, profile_data[1:]):
        body_workplane = body_workplane.workplane(offset=offset)
        body_workplane = body_workplane.polyline(
            rounded_rectangle_points(profile[0], profile[1], profile[2])
        ).close()

    plug_body = body_workplane.loft(combine=True, ruled=False).val()

    # A real CEE 7/16 Europlug uses two parallel round pins, 4 mm in diameter,
    # on 19 mm centers. The roots overlap the molded body for robust fusion.
    pin_spacing = 19.0
    pin_radius = 2.0
    pin_start_axial = 22.0
    shank_length = 20.5
    tip_length = 1.5
    direction = cq.Vector(*axis)

    new_plug = plug_body
    for lateral in (-pin_spacing / 2.0, pin_spacing / 2.0):
        pin_start = cq.Vector(*point_at(pin_start_axial, lateral))
        tip_start = cq.Vector(*point_at(pin_start_axial + shank_length, lateral))

        shank = cq.Solid.makeCylinder(
            pin_radius,
            shank_length,
            pin_start,
            direction,
        )
        chamfered_tip = cq.Solid.makeCone(
            pin_radius,
            1.65,
            tip_length,
            tip_start,
            direction,
        )

        # Slightly enlarged molded root collars reproduce the transition where
        # each metal pin enters the front face without adding extra pins.
        collar = cq.Solid.makeCone(
            2.35,
            pin_radius,
            3.0,
            pin_start,
            direction,
        )

        complete_pin = collar.fuse(shank).fuse(chamfered_tip)
        new_plug = new_plug.fuse(complete_pin)

    result = cq.Compound.makeCompound(preserved + [new_plug])

    print("Replaced source SOLID 19 with a CEE 7/16-style Europlug")
    print("Source solid count:", len(solids))
    print("Preserved non-target source solids:", len(preserved))
    print("Europlug pin count: 2")
    print("Pin geometry: round, 4.0 mm diameter")
    print("Pin center spacing: 19.0 mm")
    print("Replacement plug valid:", new_plug.isValid())
    print("Result compound valid:", result.isValid())

    return cq.Workplane(obj=result)
