def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model
    solids = shape.Solids()

    if len(solids) < 20:
        raise ValueError(f"Expected at least 20 solids in the source model, found {len(solids)}")

    # Preserve every original solid except SOLID 19, which is the existing plug.
    preserved = [solid for i, solid in enumerate(solids) if i != 19]

    # Grounded from the original cord-to-plug interface (FACE 384).
    # The local plug axis points away from the cord toward the receptacle pins.
    rear = (-152.385, 31.750, -266.704)
    axis = (-0.234, 0.0, -0.972)
    transverse = (0.972, 0.0, -0.234)

    def point_at(axial, lateral=0.0, y_offset=0.0):
        return (
            rear[0] + axis[0] * axial + transverse[0] * lateral,
            rear[1] + y_offset,
            rear[2] + axis[2] * axial + transverse[2] * lateral,
        )

    # A flattened, rounded and tapered CEE 7/16-style body. The narrow rear
    # section acts as a strain-relief transition from the preserved power cord.
    body_plane = cq.Plane(
        origin=point_at(-1.0),
        xDir=transverse,
        normal=axis,
    )
    plug_body = (
        cq.Workplane(body_plane)
        .roundedRect(8.0, 5.2, 1.8)
        .workplane(offset=5.0)
        .roundedRect(21.0, 8.0, 3.3)
        .workplane(offset=8.0)
        .roundedRect(32.0, 10.0, 4.2)
        .workplane(offset=6.0)
        .roundedRect(30.0, 8.2, 3.6)
        .loft(combine=True, ruled=False)
        .val()
    )

    # Standard recognizable Europlug mating geometry: exactly two parallel,
    # round 4 mm pins on 19 mm centers. Each pin has a subtly chamfered tip.
    pin_spacing = 19.0
    pin_radius = 2.0
    pin_start_axial = 17.2
    straight_length = 18.0
    tip_length = 1.5

    new_plug = plug_body
    for lateral in (-pin_spacing / 2.0, pin_spacing / 2.0):
        start = cq.Vector(*point_at(pin_start_axial, lateral))
        direction = cq.Vector(*axis)

        pin_shank = cq.Solid.makeCylinder(
            pin_radius,
            straight_length,
            start,
            direction,
        )
        tip_start = cq.Vector(*point_at(pin_start_axial + straight_length, lateral))
        pin_tip = cq.Solid.makeCone(
            pin_radius,
            1.65,
            tip_length,
            tip_start,
            direction,
        )

        # Slight root collar gives a realistic molded transition while retaining
        # one clearly identifiable round pin at each of the two locations.
        collar = cq.Solid.makeCylinder(
            2.35,
            2.8,
            start,
            direction,
        )
        complete_pin = collar.fuse(pin_shank).fuse(pin_tip)
        new_plug = new_plug.fuse(complete_pin)

    result = cq.Compound.makeCompound(preserved + [new_plug])

    print("Replaced original SOLID 19 with a CEE 7/16-style Europlug")
    print("Preserved original solids:", len(preserved))
    print("Europlug round pin count: 2")
    print("Pin diameter: 4.0 mm")
    print("Pin center spacing: 19.0 mm")
    print("Pin exposed length: 19.5 mm including chamfered tip")
    print("Result valid:", result.isValid())

    return cq.Workplane(obj=result)
