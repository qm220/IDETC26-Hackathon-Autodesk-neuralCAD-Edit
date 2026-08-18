def my_cad_function(args):
    import os
    shape = cq.importers.importStep(os.path.expanduser(args['input_file']))
    solid = shape.val()
    bb = solid.BoundingBox()
    print('VALID', solid.isValid())
    print('VOLUME', round(solid.Volume(), 3))
    print('BBOX', round(bb.xmin, 3), round(bb.xmax, 3), round(bb.ymin, 3), round(bb.ymax, 3), round(bb.zmin, 3), round(bb.zmax, 3))
    print('CENTER', round(bb.center.x, 3), round(bb.center.y, 3), round(bb.center.z, 3))
    print('COUNTS faces edges vertices', len(solid.Faces()), len(solid.Edges()), len(solid.Vertices()))

    for i, face in enumerate(solid.Faces()):
        c = face.Center()
        fbb = face.BoundingBox()
        try:
            gt = face.geomType()
        except Exception:
            gt = 'UNKNOWN'
        try:
            n = face.normalAt(c)
            normal = (round(n.x, 3), round(n.y, 3), round(n.z, 3))
        except Exception:
            normal = None
        print('FACE', i, gt, 'area', round(face.Area(), 3),
              'center', (round(c.x, 3), round(c.y, 3), round(c.z, 3)),
              'normal', normal,
              'size', (round(fbb.xlen, 3), round(fbb.ylen, 3), round(fbb.zlen, 3)))

    print('EDGE SUMMARY')
    for i, edge in enumerate(solid.Edges()):
        c = edge.Center()
        ebb = edge.BoundingBox()
        try:
            gt = edge.geomType()
        except Exception:
            gt = 'UNKNOWN'
        print('EDGE', i, gt, 'len', round(edge.Length(), 3),
              'center', (round(c.x, 3), round(c.y, 3), round(c.z, 3)),
              'size', (round(ebb.xlen, 3), round(ebb.ylen, 3), round(ebb.zlen, 3)))
    return shape