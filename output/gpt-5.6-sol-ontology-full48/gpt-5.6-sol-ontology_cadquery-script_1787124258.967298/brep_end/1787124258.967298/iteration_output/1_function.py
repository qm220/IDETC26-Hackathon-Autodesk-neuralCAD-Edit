def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model
    solids = list(shape.Solids())

    print("=== Europlug replacement ===")
    print(f"Input valid: {shape.isValid()}, solids={len(solids)}, faces={len(shape.Faces())}")

    # Bind the current plug to imported geometry rather than relying only on its
    # planning-stage index. It is the small terminal solid nearest FACE 412 and
    # beyond the remote end of the flexible cord.
    plug_candidates = []
    for i, solid in enumerate(solids):
        bb = solid.BoundingBox()
        c = solid.Center()
        if bb.zmax < -250.0 and bb.xmax < -135.0:
            plug_candidates.append((i, solid, c, bb))
            print(
                f"Terminal candidate SOLID {i}: center=({c.x:.3f},{c.y:.3f},{c.z:.3f}), "
                f"bbox=x({bb.xmin:.3f},{bb.xmax:.3f}) "
                f"y({bb.ymin:.3f},{bb.ymax:.3f}) z({bb.zmin:.3f},{bb.zmax:.3f})"
            )

    if not plug_candidates:
        raise ValueError("Could not bind the existing terminal plug solid")

    # The plug has a compact terminal bbox; the cord has a much larger swept bbox.
    old_plug_index, old_plug, _, _ = min(
        plug_candidates,
        key=lambda item: (
            item[3].xlen + item[3].ylen + item[3].zlen,
            item[1].Volume(),
        ),
    )
    print(f"Replacing SOLID {old_plug_index}, volume={old_plug.Volume():.3f}")

    # Frame obtained from the inspected original terminal face and prongs.
    # u is across the two pins; d points outward along the pins.
    u = cq.Vector(0.976296, 0.0, -0.216440)
    d = cq.Vector(-0.216440, 0.0, -0.976296)
    n = cq.Vector(0.0, 1.0, 0.0)

    # The end of the retained cord is centered here. Positioning the replacement
    # from this datum maintains attachment while providing room for a realistic
    # 29 mm long Europlug body.
    cable_entry = cq.Vector(-152.3851, 31.7500, -266.7036)
    front_center = cable_entry + d.multiply(29.0)

    # CEE 7/16-like flattened and tapered body. The sketch coordinates are:
    # x = transverse pin-spacing direction, y = pin-axis direction. Negative
    # sketch-y runs from the terminal face back toward the cable.
    body_plane = cq.Plane(
        origin=(front_center.x, 25.0, front_center.z),
        xDir=(u.x, u.y, u.z),
        normal=(n.x, n.y, n.z),
    )
    profile = [
        (-16.5, 0.0),
        (-17.75, -1.6),
        (-17.3, -8.5),
        (-14.4, -16.5),
        (-9.2, -24.0),
        (-5.0, -29.0),
        (5.0, -29.0),
        (9.2, -24.0),
        (14.4, -16.5),
        (17.3, -8.5),
        (17.75, -1.6),
        (16.5, 0.0),
    ]
    body_wp = cq.Workplane(body_plane).polyline(profile).close().extrude(13.5)

    # Soften the molded body's perimeter and thickness edges. Retain the base
    # body if a particular OCC build cannot fillet every imported-style edge.
    try:
        body_wp = body_wp.edges().fillet(1.25)
    except Exception as exc:
        print(f"Body fillet fallback: {exc}")
    body_shape = body_wp.val()

    # Tapered strain-relief boot directed from the narrow rear of the plug into
    # the retained flexible lead. It overlaps both parts to avoid a visual gap.
    boot_start = front_center - d.multiply(26.0)
    boot = cq.Solid.makeCone(4.8, 3.0, 12.0, boot_start, -d)
    try:
        body_shape = body_shape.fuse(boot)
    except Exception as exc:
        print(f"Boot fuse fallback: {exc}")

    replacement_parts = [body_shape]

    # Standard Europlug geometry: two parallel round pins, 4 mm diameter,
    # 19 mm center spacing and approximately 19 mm exposed length.
    pin_radius = 2.0
    pin_spacing = 19.0
    exposed_length = 19.0

    for side in (-1.0, 1.0):
        pin_axis_point = front_center + u.multiply(side * pin_spacing / 2.0)

        # Molded circular support boss at each pin root.
        collar_base = pin_axis_point - d.multiply(1.2)
        collar = cq.Solid.makeCylinder(3.25, 2.2, collar_base, d)
        try:
            body_shape = body_shape.fuse(collar)
            replacement_parts[0] = body_shape
        except Exception as exc:
            print(f"Collar fuse fallback on side {side}: {exc}")
            replacement_parts.append(collar)

        # Embed 0.8 mm into the body, then use a short tapered end treatment so
        # the pin does not terminate as a sharp-edged rectangular-looking blade.
        pin_base = pin_axis_point - d.multiply(0.8)
        straight_length = exposed_length - 0.8
        pin_cylinder = cq.Solid.makeCylinder(pin_radius, straight_length + 0.8, pin_base, d)
        tip_base = pin_axis_point + d.multiply(straight_length)
        pin_tip = cq.Solid.makeCone(pin_radius, 1.15, 0.8, tip_base, d)
        try:
            round_pin = pin_cylinder.fuse(pin_tip)
        except Exception:
            round_pin = cq.Compound.makeCompound([pin_cylinder, pin_tip])
        replacement_parts.append(round_pin)

    # Preserve the complete original assembly except for the old flat-blade plug.
    retained = [solid for i, solid in enumerate(solids) if i != old_plug_index]
    result = cq.Compound.makeCompound(retained + replacement_parts)

    rb = result.BoundingBox()
    print(
        f"Result valid={result.isValid()}, solids={len(result.Solids())}, "
        f"bbox=x({rb.xmin:.3f},{rb.xmax:.3f}) "
        f"y({rb.ymin:.3f},{rb.ymax:.3f}) z({rb.zmin:.3f},{rb.zmax:.3f})"
    )
    print("Europlug parameters: 2 round pins, diameter=4.0 mm, spacing=19.0 mm, exposed length=19.0 mm")

    return cq.Workplane(obj=result)
