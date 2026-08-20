def my_cad_function(args):
    import os
    import math
    import cadquery as cq

    input_file = os.path.expanduser(args['input_file'])
    imported = cq.importers.importStep(input_file)
    solids = imported.val().Solids()
    if len(solids) < 2:
        raise ValueError('Expected the separate center insert and sprocket carrier as two solids')

    insert = solids[0]
    carrier = solids[1]

    # Axial direction is global Y in the imported STEP. These limits correspond
    # to the existing flower-shaped insert/socket interface identified from the
    # original planar shoulders.
    y0 = -4.62502
    y1 = 0.17498
    interface_height = y1 - y0

    # A regular hexagon sized within the nominal envelope of the former lobed
    # interface. The carrier receives a small radial clearance around the insert.
    insert_hex_radius = 14.00
    socket_hex_radius = 14.04
    rebuild_radius = 15.75

    def regular_hex_prism(radius, start_y, height):
        # Vertices at 0, 60, ... degrees give horizontal top and bottom flats
        # when viewed along the Y axis.
        points = []
        for i in range(6):
            a = math.radians(60.0 * i)
            points.append(cq.Vector(radius * math.cos(a), start_y,
                                    radius * math.sin(a)))
        wire = cq.Wire.makePolygon(points, close=True)
        return cq.Solid.extrudeLinear(wire, [], cq.Vector(0, height, 0))

    # Recover the exact existing internal-spline void from the original insert.
    # Only the void component containing the rotational axis is retained, so the
    # spline tooth form, count, orientation and axial extent remain unchanged.
    probe_margin = 0.10
    spline_probe = cq.Solid.makeCylinder(
        12.0,
        interface_height + 2.0 * probe_margin,
        cq.Vector(0, y0 - probe_margin, 0),
        cq.Vector(0, 1, 0)
    )
    void_candidates = spline_probe.cut(insert).Solids()
    if not void_candidates:
        raise ValueError('Unable to recover the existing internal spline void')

    axis_point = cq.Vector(0, (y0 + y1) * 0.5, 0)
    central_void = None
    for candidate in void_candidates:
        try:
            if candidate.isInside(axis_point, 1.0e-6, True):
                central_void = candidate
                break
        except Exception:
            pass

    if central_void is None:
        # Fallback: the spline void is the component whose transverse bounding
        # box is most nearly centered on the model axis.
        def center_score(shape):
            bb = shape.BoundingBox()
            return abs((bb.xmin + bb.xmax) * 0.5) + abs((bb.zmin + bb.zmax) * 0.5)
        central_void = min(void_candidates, key=center_score)

    # Remove the old lobed portion of the separate insert. A slight overlap at
    # the upper shoulder ensures a robust union with the preserved circular
    # front pilot while retaining all geometry outside the interface depth.
    removal_tool = cq.Solid.makeCylinder(
        30.0,
        interface_height + 0.002,
        cq.Vector(0, y0 - 0.001, 0),
        cq.Vector(0, 1, 0)
    )
    preserved_insert = insert.cut(removal_tool)

    new_hex_insert = regular_hex_prism(
        insert_hex_radius,
        y0,
        interface_height + 0.006
    ).cut(central_void)
    modified_insert = preserved_insert.fuse(new_hex_insert)

    # Restore material in the carrier's former flower-shaped socket, then form
    # a matching regular-hexagonal socket. The operation is limited to the old
    # interface depth and radius, preserving the rear circular boss, spider,
    # openings, rim and sprocket teeth.
    socket_fill = cq.Solid.makeCylinder(
        rebuild_radius,
        interface_height,
        cq.Vector(0, y0, 0),
        cq.Vector(0, 1, 0)
    )
    socket_tool = regular_hex_prism(
        socket_hex_radius,
        y0 - 0.01,
        interface_height + 0.02
    )
    modified_carrier = carrier.fuse(socket_fill).cut(socket_tool)

    if not modified_insert.isValid():
        raise ValueError('Modified hexagonal center insert is invalid')
    if not modified_carrier.isValid():
        raise ValueError('Modified sprocket carrier is invalid')

    print('Replaced center flower interface with concentric regular hexagon')
    print('Insert hex across corners:', 2.0 * insert_hex_radius)
    print('Insert hex across flats:', math.sqrt(3.0) * insert_hex_radius)
    print('Interface Y range:', (y0, y1))
    print('Internal spline recovered unchanged from original insert')
    print('Modified insert volume:', modified_insert.Volume())
    print('Modified carrier volume:', modified_carrier.Volume())

    result = cq.Compound.makeCompound([modified_insert, modified_carrier])
    return cq.Workplane('XY').newObject([result])