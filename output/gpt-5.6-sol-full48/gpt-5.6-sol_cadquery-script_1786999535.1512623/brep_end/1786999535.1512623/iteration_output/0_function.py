def my_cad_function(args):
    input_file = os.path.expanduser(args['input_file'])
    model = cq.importers.importStep(input_file)
    shape = model.val()
    bb = shape.BoundingBox()
    c = bb.center
    print('VALID', shape.isValid())
    print('VOLUME %.6f' % shape.Volume())
    print('BBOX min=(%.4f, %.4f, %.4f) max=(%.4f, %.4f, %.4f) size=(%.4f, %.4f, %.4f) center=(%.4f, %.4f, %.4f)' % (bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax, bb.xlen, bb.ylen, bb.zlen, c.x, c.y, c.z))
    print('SOLIDS', len(shape.Solids()), 'FACES', len(shape.Faces()), 'EDGES', len(shape.Edges()))

    print('--- CYLINDRICAL FACES ---')
    for i, face in enumerate(shape.Faces()):
        try:
            gt = face.geomType()
        except Exception:
            gt = 'UNKNOWN'
        if gt == 'CYLINDER':
            fc = face.Center()
            fb = face.BoundingBox()
            try:
                radius = face.radius()
            except Exception:
                radius = -1.0
            print('FACE %d type=%s center=(%.4f,%.4f,%.4f) area=%.5f radius=%.5f bbox=(%.4f,%.4f,%.4f)-(%.4f,%.4f,%.4f)' % (i, gt, fc.x, fc.y, fc.z, face.Area(), radius, fb.xmin, fb.ymin, fb.zmin, fb.xmax, fb.ymax, fb.zmax))

    print('--- CIRCULAR EDGES ---')
    for i, edge in enumerate(shape.Edges()):
        try:
            gt = edge.geomType()
        except Exception:
            gt = 'UNKNOWN'
        if gt == 'CIRCLE':
            ec = edge.Center()
            eb = edge.BoundingBox()
            try:
                radius = edge.radius()
            except Exception:
                radius = -1.0
            try:
                tan = edge.tangentAt(0.15)
                ttext = '(%.3f,%.3f,%.3f)' % (tan.x, tan.y, tan.z)
            except Exception:
                ttext = 'n/a'
            print('EDGE %d center=(%.4f,%.4f,%.4f) radius=%.5f length=%.5f tangent=%s bbox=(%.4f,%.4f,%.4f)-(%.4f,%.4f,%.4f)' % (i, ec.x, ec.y, ec.z, radius, edge.Length(), ttext, eb.xmin, eb.ymin, eb.zmin, eb.xmax, eb.ymax, eb.zmax))

    print('--- LARGE PLANAR FACES ---')
    planar = []
    for i, face in enumerate(shape.Faces()):
        try:
            if face.geomType() == 'PLANE':
                planar.append((face.Area(), i, face))
        except Exception:
            pass
    planar.sort(key=lambda item: item[0], reverse=True)
    for area, i, face in planar[:40]:
        fc = face.Center()
        fb = face.BoundingBox()
        try:
            n = face.normalAt()
            ntext = '(%.4f,%.4f,%.4f)' % (n.x, n.y, n.z)
        except Exception:
            ntext = 'n/a'
        print('FACE %d center=(%.4f,%.4f,%.4f) area=%.5f normal=%s bbox=(%.4f,%.4f,%.4f)-(%.4f,%.4f,%.4f)' % (i, fc.x, fc.y, fc.z, area, ntext, fb.xmin, fb.ymin, fb.zmin, fb.xmax, fb.ymax, fb.zmax))
    return model