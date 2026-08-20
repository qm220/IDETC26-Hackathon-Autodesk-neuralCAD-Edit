def my_cad_function(args):
    input_file = os.path.expanduser(args['input_file'])
    model = cq.importers.importStep(input_file)
    shape = model.val()
    bb = shape.BoundingBox()
    print('VALID', shape.isValid(), 'VOLUME', shape.Volume())
    print('BBOX', bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax)
    print('FACES', len(shape.Faces()), 'EDGES', len(shape.Edges()), 'SOLIDS', len(shape.Solids()))
    for i, face in enumerate(shape.Faces()):
        c = face.Center()
        fb = face.BoundingBox()
        try:
            n = face.normalAt()
            normal = (round(n.x, 3), round(n.y, 3), round(n.z, 3))
        except Exception:
            normal = None
        print('FACE', i, face.geomType(), 'area', round(face.Area(), 3),
              'center', (round(c.x, 3), round(c.y, 3), round(c.z, 3)),
              'normal', normal,
              'bbox', (round(fb.xmin, 3), round(fb.xmax, 3), round(fb.ymin, 3), round(fb.ymax, 3), round(fb.zmin, 3), round(fb.zmax, 3)))
    for i, edge in enumerate(shape.Edges()):
        eb = edge.BoundingBox()
        c = edge.Center()
        print('EDGE', i, edge.geomType(), 'len', round(edge.Length(), 3),
              'center', (round(c.x, 3), round(c.y, 3), round(c.z, 3)),
              'bbox', (round(eb.xmin, 3), round(eb.xmax, 3), round(eb.ymin, 3), round(eb.ymax, 3), round(eb.zmin, 3), round(eb.zmax, 3)))
    return model