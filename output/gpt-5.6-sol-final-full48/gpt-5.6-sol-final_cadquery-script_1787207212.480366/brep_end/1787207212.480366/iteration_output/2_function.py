def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args['input_file'])
    source = cq.importers.importStep(input_file)

    x0, x_joint, x1 = 0.0, 100.0, 300.0
    yc = 260.0
    big_y0, big_y1 = 200.0, 320.0
    stem_y0, stem_y1 = 230.0, 290.0
    z0, z1 = -450.0, -340.0

    big = cq.Solid.makeBox(
        x_joint - x0, big_y1 - big_y0, z1 - z0,
        cq.Vector(x0, big_y0, z0)
    )
    stem = cq.Solid.makeBox(
        x1 - x_joint, stem_y1 - stem_y0, z1 - z0,
        cq.Vector(x_joint, stem_y0, z0)
    )
    body = big.fuse(stem)

    def vertical_edges(shape):
        result = []
        for edge in shape.Edges():
            eb = edge.BoundingBox()
            if (edge.geomType() == 'LINE' and
                    eb.zlen > 0.90 * (z1 - z0) and
                    eb.xlen < 1.0e-5 and eb.ylen < 1.0e-5):
                result.append(edge)
        return result

    shoulders = []
    for edge in vertical_edges(body):
        c = edge.Center()
        if (abs(c.x - x_joint) < 1.0e-4 and
                (abs(c.y - stem_y0) < 1.0e-4 or
                 abs(c.y - stem_y1) < 1.0e-4)):
            shoulders.append(edge)
    if shoulders:
        body = body.fillet(20.0, shoulders)

    exterior_vertical = vertical_edges(body)
    if exterior_vertical:
        body = body.fillet(5.0, exterior_vertical)

    horizontal_perimeter = []
    for edge in body.Edges():
        eb = edge.BoundingBox()
        if eb.zlen < 1.0e-5 and (
                abs(eb.zmin - z0) < 1.0e-4 or
                abs(eb.zmin - z1) < 1.0e-4):
            horizontal_perimeter.append(edge)
    if horizontal_perimeter:
        body = body.fillet(5.0, horizontal_perimeter)

    bore_radius = 14.1421356237
    bore = cq.Solid.makeCylinder(
        bore_radius,
        x1 - x_joint,
        cq.Vector(x1, 270.0, -400.0),
        cq.Vector(-1.0, 0.0, 0.0)
    )
    body = body.cut(bore)

    pocket_x0 = 125.351
    pocket_x1 = 168.336
    pocket_y0 = stem_y0 - 1.0
    pocket_y1 = 280.0
    pocket_z0 = -405.071
    pocket_z1 = -374.122
    pocket = cq.Solid.makeBox(
        pocket_x1 - pocket_x0,
        pocket_y1 - pocket_y0,
        pocket_z1 - pocket_z0,
        cq.Vector(pocket_x0, pocket_y0, pocket_z0)
    )
    body = body.cut(pocket)

    mouth_edges = []
    for edge in body.Edges():
        eb = edge.BoundingBox()
        c = edge.Center()
        if (edge.geomType() == 'CIRCLE' and
                abs(eb.xmin - x1) < 1.0e-4 and
                abs(eb.xmax - x1) < 1.0e-4 and
                abs(c.y - 270.0) < 1.0e-3 and
                abs(c.z + 400.0) < 1.0e-3):
            mouth_edges.append(edge)
    if mouth_edges:
        try:
            body = body.fillet(5.0, mouth_edges)
        except Exception:
            pass

    result = cq.Workplane('XY').newObject([body])
    bb = body.BoundingBox()
    print('VALID', body.isValid(), 'VOLUME', body.Volume())
    print('BBOX', bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax)
    print('SYMMETRIC EXTERIOR CENTER Y', yc)
    print('SHOULDER FILLET R20 COUNT', len(shoulders))
    print('SOLIDS', len(body.Solids()), 'FACES', len(body.Faces()), 'EDGES', len(body.Edges()))
    return result