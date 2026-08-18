def my_cad_function(args):
    input_file = os.path.expanduser(args['input_file'])
    model = cq.importers.importStep(input_file)
    shape = model.val()
    bbox = shape.BoundingBox()
    print('MODEL valid=', shape.isValid(), 'solids=', len(shape.Solids()), 'faces=', len(shape.Faces()))
    print('MODEL bbox:', (bbox.xmin, bbox.ymin, bbox.zmin), (bbox.xmax, bbox.ymax, bbox.zmax))

    # Inspect every disconnected solid to localize the existing shallow,
    # elongated horizontal button and determine the model coordinate system.
    records = []
    for i, solid in enumerate(shape.Solids()):
        b = solid.BoundingBox()
        c = b.center
        records.append((i, solid.Volume(), c.x, c.y, c.z, b.xlen, b.ylen, b.zlen))
    for rec in sorted(records, key=lambda r: r[0]):
        print('SOLID %02d volume=%10.3f center=(%8.3f,%8.3f,%8.3f) size=(%8.3f,%8.3f,%8.3f)' % rec)

    # List likely button candidates: comparatively small solids having one long,
    # one medium, and one shallow bounding-box dimension.
    print('BUTTON CANDIDATES:')
    for rec in records:
        dims = sorted(rec[5:8])
        if 0.3 <= dims[0] <= 8.0 and 2.0 <= dims[1] <= 20.0 and 6.0 <= dims[2] <= 45.0:
            print('  candidate', rec)

    return model