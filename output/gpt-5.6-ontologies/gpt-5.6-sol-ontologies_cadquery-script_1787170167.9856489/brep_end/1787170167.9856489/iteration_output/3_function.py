def my_cad_function(args):
    import os
    import math
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    shape = imported.val() if hasattr(imported, "val") else imported

    solids = list(shape.Solids())
    if len(solids) != 2:
        raise ValueError("Expected two source solids, found %d" % len(solids))

    solids.sort(key=lambda s: s.Volume())
    insert_original = solids[0]
    body_original = solids[1]

    ibb = insert_original.BoundingBox()
    center = ibb.center
    axis = cq.Vector(0.0, 1.0, 0.0)

    # The source wheel axis is Y. The flower-shaped rear interface occupies
    # the smaller insert from its rear face to the circular front flange.
    rear_y = ibb.ymin
    interface_front_y = ibb.ymin + 4.8
    interface_depth = interface_front_y - rear_y

    # Unite the original material first. This removes the old solid-to-solid
    # assignment while retaining all sprocket, web, hub and spline geometry.
    total_original = body_original.fuse(insert_original).clean()

    # The visible flower profile includes a shallow sculpted/recessed annulus.
    # Heal that targeted annulus to a planar circular hub region before making
    # the new partition; otherwise the old flower edges remain visible even
    # when only the solid ownership is changed. The spline void is recovered
    # exactly from the source model and is therefore not filled.
    patch_radius = 15.2
    bore_capture_radius = 11.3
    patch_base = cq.Vector(center.x, rear_y, center.z)

    patch_zone = cq.Solid.makeCylinder(
        patch_radius, interface_depth, patch_base, axis
    )
    bore_capture = cq.Solid.makeCylinder(
        bore_capture_radius, interface_depth, patch_base, axis
    )

    # Empty space inside the bore-capture cylinder represents the detailed
    # internal spline void. Subtract it from the healing patch verbatim.
    spline_void = bore_capture.cut(total_original)
    healed_patch = patch_zone.cut(spline_void)
    total_healed = total_original.fuse(healed_patch).clean()

    # Create a regular six-sided torque interface. Its 14 mm circumradius
    # gives a 12.124 mm apothem, clearing the spline while remaining within
    # the surrounding circular hub envelope.
    hex_radius = 14.0
    eps = 0.05
    hex_y0 = rear_y - eps
    hex_y1 = interface_front_y
    hex_points = []
    for i in range(6):
        angle = math.radians(60.0 * i)
        hex_points.append(cq.Vector(
            center.x + hex_radius * math.cos(angle),
            hex_y0,
            center.z + hex_radius * math.sin(angle)
        ))

    hex_wire = cq.Wire.makePolygon(hex_points, close=True)
    hex_prism = cq.Solid.extrudeLinear(
        hex_wire, [], cq.Vector(0.0, hex_y1 - hex_y0, 0.0)
    )

    # Preserve the original circular front flange of the insert exactly.
    margin = 2.0
    front_box = cq.Solid.makeBox(
        ibb.xlen + 2.0 * margin,
        ibb.ymax - interface_front_y + margin,
        ibb.zlen + 2.0 * margin,
        cq.Vector(
            ibb.xmin - margin,
            interface_front_y,
            ibb.zmin - margin
        )
    )
    insert_front = insert_original.intersect(front_box)

    # Repartition the healed center into a true hexagonal rear insert and its
    # complementary sprocket body. The detailed through-spline remains empty.
    insert_hex = total_healed.intersect(hex_prism)
    insert_new = insert_front.fuse(insert_hex).clean()
    body_new = total_healed.cut(insert_new).clean()

    if not insert_new.isValid() or not body_new.isValid():
        raise ValueError("Hexagonal center replacement produced invalid geometry")
    if len(insert_new.Solids()) != 1 or len(body_new.Solids()) != 1:
        raise ValueError(
            "Expected one insert and one body solid; got %d and %d" %
            (len(insert_new.Solids()), len(body_new.Solids()))
        )

    result_shape = cq.Compound.makeCompound([body_new, insert_new])
    if not result_shape.isValid():
        raise ValueError("Resulting compound is invalid")

    result = cq.Workplane("XY").newObject([result_shape])

    original_volume = insert_original.Volume() + body_original.Volume()
    final_volume = insert_new.Volume() + body_new.Volume()
    bb = result_shape.BoundingBox()
    print("CENTER_REPLACEMENT old=flower new=regular_hexagon")
    print("HEX center_xz=(%.4f, %.4f) R=%.4f apothem=%.4f y=(%.4f, %.4f)" % (
        center.x, center.z, hex_radius,
        hex_radius * math.cos(math.radians(30.0)),
        rear_y, interface_front_y
    ))
    print("HEALED_TARGET patch_radius=%.4f bore_capture_radius=%.4f added_volume=%.9f" % (
        patch_radius, bore_capture_radius, final_volume - original_volume
    ))
    print("RESULT valid=%s solids=%d bbox=(%.4f,%.4f,%.4f)-(%.4f,%.4f,%.4f)" % (
        result_shape.isValid(), len(result_shape.Solids()),
        bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax
    ))

    return result