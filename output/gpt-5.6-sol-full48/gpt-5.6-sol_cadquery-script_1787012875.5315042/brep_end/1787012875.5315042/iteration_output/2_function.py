def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    source_shape = imported.val()

    retained = []
    removed = []
    for solid in source_shape.Solids():
        c = solid.Center()
        bb = solid.BoundingBox()
        is_old_plug = (
            c.x < -140.0 and
            c.z < -250.0 and
            solid.Volume() < 12000.0 and
            bb.ylen < 10.0
        )
        if is_old_plug:
            removed.append(solid)
        else:
            retained.append(solid)

    print("Removed old plug solids:", len(removed))
    print("Retained source solids:", len(retained))

    u = cq.Vector(-0.3420, 0.0, -0.9397)
    v = cq.Vector(0.9397, 0.0, -0.3420)
    nose = cq.Vector(-157.50, 33.02, -281.45)

    plug_plane = cq.Plane(
        origin=(nose.x, nose.y, nose.z),
        xDir=(v.x, v.y, v.z),
        normal=(u.x, u.y, u.z)
    )

    body = (
        cq.Workplane(plug_plane)
        .ellipse(14.8, 6.2)
        .workplane(offset=-4.0)
        .ellipse(16.5, 7.4)
        .workplane(offset=-5.0)
        .ellipse(16.0, 7.2)
        .workplane(offset=-5.0)
        .ellipse(13.5, 6.3)
        .workplane(offset=-4.0)
        .ellipse(9.0, 4.7)
        .loft(combine=True, ruled=False)
        .val()
    )

    rear_center = nose - u.multiply(18.0)
    relief_plane = cq.Plane(
        origin=(rear_center.x, rear_center.y, rear_center.z),
        xDir=(v.x, v.y, v.z),
        normal=(u.x, u.y, u.z)
    )
    relief = (
        cq.Workplane(relief_plane)
        .ellipse(8.8, 4.6)
        .workplane(offset=-2.5)
        .ellipse(6.0, 3.2)
        .workplane(offset=-2.5)
        .ellipse(4.1, 2.0)
        .loft(combine=True, ruled=False)
        .val()
    )

    pin_parts = []
    pin_spacing = 19.0
    pin_radius = 2.0
    sleeve_radius = 2.08
    sleeve_length = 8.0
    straight_metal_length = 10.0
    tip_length = 1.0

    for side in (-1.0, 1.0):
        root = nose + v.multiply(side * pin_spacing / 2.0)

        sleeve = cq.Solid.makeCylinder(
            sleeve_radius,
            sleeve_length,
            root,
            u
        )

        metal_start = root + u.multiply(sleeve_length)
        metal = cq.Solid.makeCylinder(
            pin_radius,
            straight_metal_length,
            metal_start,
            u
        )

        tip_start = metal_start + u.multiply(straight_metal_length)
        tip = cq.Solid.makeCone(
            pin_radius,
            1.55,
            tip_length,
            tip_start,
            u
        )

        pin_parts.extend([sleeve, metal, tip])

    result_parts = retained + [body, relief] + pin_parts
    result = cq.Compound.makeCompound(result_parts)

    print("Europlug body length: 23 mm including strain relief")
    print("Europlug maximum body width: 33 mm")
    print("Pin diameter: 4 mm")
    print("Pin center spacing: 19 mm")
    print("Pin projection: 19 mm")
    print("Result solid count:", len(result.Solids()))
    print("Result valid:", result.isValid())

    return cq.Workplane("XY").newObject([result])