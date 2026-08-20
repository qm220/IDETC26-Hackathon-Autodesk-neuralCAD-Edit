def my_cad_function(args):
    input_file = os.path.expanduser(args['input_file'])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, 'val') else model

    bb = shape.BoundingBox()
    print('MODEL VALID:', shape.isValid())
    print('MODEL VOLUME:', shape.Volume())
    print('MODEL BBOX:', (bb.xmin, bb.ymin, bb.zmin), (bb.xmax, bb.ymax, bb.zmax))
    print('MODEL CENTER:', (bb.center.x, bb.center.y, bb.center.z))
    print('COUNTS faces/edges/vertices:', len(shape.Faces()), len(shape.Edges()), len(shape.Vertices()))

    print('\n=== FACE ANALYSIS (CadQuery Faces() order) ===')
    for i, face in enumerate(shape.Faces()):
        c = face.Center()
        fb = face.BoundingBox()
        try:
            gt = face.geomType()
        except Exception:
            gt = 'UNKNOWN'
        try:
            n = face.normalAt(c)
            normal = (round(n.x, 6), round(n.y, 6), round(n.z, 6))
        except Exception:
            normal = None
        print(
            'FACE %d type=%s area=%.6f center=(%.6f,%.6f,%.6f) normal=%s '
            'bbox=[(%.6f,%.6f,%.6f),(%.6f,%.6f,%.6f)] edges=%d' % (
                i, gt, face.Area(), c.x, c.y, c.z, normal,
                fb.xmin, fb.ymin, fb.zmin, fb.xmax, fb.ymax, fb.zmax,
                len(face.Edges())
            )
        )

    print('\n=== EDGE ANALYSIS (CadQuery Edges() order) ===')
    for i, edge in enumerate(shape.Edges()):
        c = edge.Center()
        eb = edge.BoundingBox()
        verts = edge.Vertices()
        ends = [(round(v.X, 5), round(v.Y, 5), round(v.Z, 5)) for v in verts]
        try:
            gt = edge.geomType()
        except Exception:
            gt = 'UNKNOWN'
        try:
            tangent = edge.tangentAt(0.5)
            tan = (round(tangent.x, 6), round(tangent.y, 6), round(tangent.z, 6))
        except Exception:
            tan = None
        print(
            'EDGE %d type=%s length=%.6f center=(%.6f,%.6f,%.6f) tangent=%s '
            'ends=%s bbox=[(%.6f,%.6f,%.6f),(%.6f,%.6f,%.6f)]' % (
                i, gt, edge.Length(), c.x, c.y, c.z, tan, ends,
                eb.xmin, eb.ymin, eb.zmin, eb.xmax, eb.ymax, eb.zmax
            )
        )

    return model