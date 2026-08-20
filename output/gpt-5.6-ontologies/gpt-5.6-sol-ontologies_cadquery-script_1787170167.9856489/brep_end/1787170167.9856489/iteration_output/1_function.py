def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    shape = imported.val() if hasattr(imported, "val") else imported

    solids = shape.Solids()
    if len(solids) != 2:
        raise ValueError("Expected two solids in the source model, found %d" % len(solids))

    # The smaller solid is the central splined insert; the larger solid is the
    # sprocket body. The flower-shaped profile is their rear mating boundary.
    solids = sorted(solids, key=lambda s: s.Volume())
    insert_original = solids[0]
    body_original = solids[1]

    ibb = insert_original.BoundingBox()
    ic = ibb.center

    # The imported insert changes from its rear flower-profile interface to its
    # preserved circular front flange at Y = 0.175 mm. Derive this location from
    # the measured insert bounds so the operation remains centered on the model.
    interface_front_y = ibb.ymin + 4.8

    # Fuse the two source solids temporarily. This removes the former flower
    # seam without changing the exterior, bore, spline teeth, web, rim, or teeth.
    total = body_original.fuse(insert_original).clean()

    # A 28 mm corner-to-corner regular hexagon gives an apothem of about
    # 12.12 mm, retaining material outside the existing spline envelope while
    # providing six planar torque-transfer faces. Its axis is the original Y axis.
    hex_radius = 14.0
    y0 = ibb.ymin - 0.5
    y1 = interface_front_y
    points = []
    for i in range(6):
        a = math.radians(60.0 * i)
        points.append(cq.Vector(
            ic.x + hex_radius * math.cos(a),
            y0,
            ic.z + hex_radius * math.sin(a)
        ))

    hex_wire = cq.Wire.makePolygon(points, close=True)
    hex_prism = cq.Solid.extrudeLinear(
        hex_wire,
        [],
        cq.Vector(0.0, y1 - y0, 0.0)
    )

    # Preserve the original circular front portion of the insert exactly.
    margin = 2.0
    front_box = cq.Solid.makeBox(
        ibb.xlen + 2.0 * margin,
        ibb.ymax - interface_front_y + margin,
        ibb.zlen + 2.0 * margin,
        cq.Vector(ibb.xmin - margin, interface_front_y, ibb.zmin - margin)
    )
    insert_front = insert_original.intersect(front_box)

    # Partition the unchanged total material using the new hexagonal interface.
    # Intersecting with `total` automatically preserves the original internal
    # splined through-bore and all of its detailed tooth geometry.
    insert_hex = total.intersect(hex_prism)
    insert_new = insert_front.fuse(insert_hex).clean()
    body_new = total.cut(insert_new).clean()

    result_shape = cq.Compound.makeCompound([body_new, insert_new])
    result = cq.Workplane("XY").newObject([result_shape])

    old_volume = insert_original.Volume() + body_original.Volume()
    new_volume = body_new.Volume() + insert_new.Volume()
    bb = result_shape.BoundingBox()
    print("HEX_PROFILE center=(%.4f, %.4f) radius=%.4f apothem=%.4f depth=(%.4f to %.4f)" % (
        ic.x, ic.z, hex_radius, hex_radius * math.cos(math.radians(30.0)),
        y0, interface_front_y))
    print("RESULT valid=%s solids=%d volume_delta=%.9f" % (
        result_shape.isValid(), len(result_shape.Solids()), new_volume - old_volume))
    print("RESULT bbox=(%.4f,%.4f,%.4f)-(%.4f,%.4f,%.4f)" % (
        bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax))

    return result