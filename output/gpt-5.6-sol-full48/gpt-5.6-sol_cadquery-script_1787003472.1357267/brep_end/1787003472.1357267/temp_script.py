def my_cad_function(args):
    import os

    input_file = os.path.expanduser(args['input_file'])
    imported = cq.importers.importStep(input_file)
    base_shape = imported.val() if hasattr(imported, 'val') else imported
    bbox = base_shape.BoundingBox()

    print('Imported radiator model')
    print('Valid:', base_shape.isValid())
    print('Faces:', len(base_shape.Faces()), 'Solids:', len(base_shape.Solids()))
    print('BBox: x=(%.3f, %.3f), y=(%.3f, %.3f), z=(%.3f, %.3f)' %
          (bbox.xmin, bbox.xmax, bbox.ymin, bbox.ymax, bbox.zmin, bbox.zmax))

    # Report individual solid envelopes so malformed legacy fittings can be
    # distinguished from the radiator, fans, feet, and cap in later refinement.
    for i, solid in enumerate(base_shape.Solids()):
        try:
            sb = solid.BoundingBox()
            print('Solid %02d: volume=%.3f bbox=[%.2f %.2f] [%.2f %.2f] [%.2f %.2f]' %
                  (i, solid.Volume(), sb.xmin, sb.xmax, sb.ymin, sb.ymax,
                   sb.zmin, sb.zmax))
        except Exception as exc:
            print('Solid %02d inspection failed: %s' % (i, exc))

    # The STEP report establishes X as radiator depth, Y as elevation, and Z
    # as left/right. Locate both ports within the end-tank bands rather than
    # the central fin field. The X coordinate is based on the reported core
    # sheets at x=-73.025 and x=-104.775 mm.
    x_port = -88.9
    overall_y = bbox.ymax - bbox.ymin
    edge_offset = max(22.0, min(35.0, overall_y * 0.10))
    y_top = bbox.ymax - edge_offset
    y_bottom = bbox.ymin + edge_offset

    z_right_wall = 266.7 if bbox.zmax >= 266.7 else bbox.zmax
    z_left_wall = -266.7 if bbox.zmin <= -266.7 else bbox.zmin

    bore_r = 6.0
    neck_r = 10.0
    barb_r = 13.0
    root_r = 15.0
    inward_overlap = 5.0
    total_length = 58.0

    def make_barbed_port(origin, direction):
        d = cq.Vector(*direction)
        p = cq.Vector(*origin)

        # Root pad and neck overlap the tank wall to make the intended
        # pressure-boundary connection unambiguous.
        outer = cq.Solid.makeCylinder(root_r, 8.0, p, d)
        outer = outer.fuse(cq.Solid.makeCylinder(neck_r, total_length, p, d))

        # Three overlapping tapered retention barbs. Each cone grows toward
        # the tank, giving a hose lead-in from the free end.
        for start in (13.0, 25.0, 37.0):
            bp = p + d.multiply(start)
            cone = cq.Solid.makeCone(barb_r, neck_r, 10.0, bp, d)
            outer = outer.fuse(cone)

        # Rounded-looking terminal collar and a reduced insertion nose.
        collar_p = p + d.multiply(47.0)
        outer = outer.fuse(cq.Solid.makeCylinder(11.0, 5.0, collar_p, d))
        nose_p = p + d.multiply(52.0)
        outer = outer.fuse(cq.Solid.makeCone(11.0, 8.5, 6.0, nose_p, d))

        # Continuous open flow passage through the port and beyond the tank
        # interface. Extending the cutter at both ends prevents residual caps.
        cutter_start = p - d.multiply(2.0)
        bore = cq.Solid.makeCylinder(bore_r, total_length + 5.0,
                                     cutter_start, d)
        return outer.cut(bore)

    # Positive-Z end, upper tank: outlet directed toward the right.
    outlet_origin = (x_port, y_top, z_right_wall - inward_overlap)
    outlet = make_barbed_port(outlet_origin, (0.0, 0.0, 1.0))

    # Negative-Z end, lower tank: inlet directed toward the left.
    inlet_origin = (x_port, y_bottom, z_left_wall + inward_overlap)
    inlet = make_barbed_port(inlet_origin, (0.0, 0.0, -1.0))

    print('Outlet center:', (x_port, y_top, z_right_wall), 'axis=+Z')
    print('Inlet center:', (x_port, y_bottom, z_left_wall), 'axis=-Z')
    print('Port dimensions: bore=12 mm, neck=20 mm, barb major=26 mm')

    # Keep the imported, topology-fragmented radiator unchanged and add the
    # rebuilt fittings as valid independent pressure-port solids. Assembly
    # output avoids unreliable Boolean operations against the invalid STEP.
    result = cq.Assembly(name='radiator_with_diagonal_ports')
    result.add(base_shape, name='radiator')
    result.add(outlet, name='top_right_outlet', color=cq.Color(0.95, 0.65, 0.15))
    result.add(inlet, name='bottom_left_inlet', color=cq.Color(0.95, 0.65, 0.15))
    return result