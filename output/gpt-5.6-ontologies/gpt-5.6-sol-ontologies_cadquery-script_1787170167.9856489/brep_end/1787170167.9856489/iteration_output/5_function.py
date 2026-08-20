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

    rear_y = ibb.ymin
    interface_front_y = ibb.ymin + 4.8
    eps = 0.05

    total_original = body_original.fuse(insert_original).clean()

    patch_radius = 15.6
    bore_capture_radius = 11.4

    cutter = cq.Solid.makeCylinder(
        patch_radius,
        interface_front_y - rear_y + 2.0 * eps,
        cq.Vector(center.x, rear_y - eps, center.z),
        axis
    )

    replacement_envelope = cq.Solid.makeCylinder(
        patch_radius,
        interface_front_y - rear_y + eps,
        cq.Vector(center.x, rear_y, center.z),
        axis
    )

    bore_capture = cq.Solid.makeCylinder(
        bore_capture_radius,
        interface_front_y - rear_y + eps,
        cq.Vector(center.x, rear_y, center.z),
        axis
    )

    spline_void = bore_capture.cut(total_original)
    replacement = replacement_envelope.cut(spline_void)
    outside_target = total_original.cut(cutter)
    total_healed = outside_target.fuse(replacement).clean()

    hex_radius = 14.0
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
        hex_wire,
        [],
        cq.Vector(0.0, hex_y1 - hex_y0, 0.0)
    )

    margin = 2.0
    front_box = cq.Solid.makeBox(
        ibb.xlen + 2.0 * margin,
        ibb.ymax - interface_front_y + margin,
        ibb.zlen + 2.0 * margin,
        cq.Vector(ibb.xmin - margin, interface_front_y, ibb.zmin - margin)
    )
    insert_front = insert_original.intersect(front_box)

    insert_hex = total_healed.intersect(hex_prism)
    insert_new = insert_front.fuse(insert_hex).clean()
    body_new = total_healed.cut(insert_new).clean()

    if not insert_new.isValid() or not body_new.isValid():
        raise ValueError("Central hexagonal replacement produced invalid geometry")
    if len(insert_new.Solids()) != 1 or len(body_new.Solids()) != 1:
        raise ValueError("Expected one insert and one body solid")

    result_shape = cq.Compound.makeCompound([body_new, insert_new])
    if not result_shape.isValid():
        raise ValueError("Resulting compound is invalid")

    return cq.Workplane("XY").newObject([result_shape])