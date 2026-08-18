def my_cad_function(args):
    input_file = os.path.expanduser(args['input_file'])
    model = cq.importers.importStep(input_file)
    shape = model.val()
    bbox = shape.BoundingBox()
    print('MODEL VALID:', shape.isValid())
    print('OVERALL BBOX: x=[%.3f, %.3f] y=[%.3f, %.3f] z=[%.3f, %.3f] size=(%.3f, %.3f, %.3f)' % (
        bbox.xmin, bbox.xmax, bbox.ymin, bbox.ymax, bbox.zmin, bbox.zmax,
        bbox.xlen, bbox.ylen, bbox.zlen))
    print('SOLIDS:', len(shape.Solids()), 'FACES:', len(shape.Faces()))

    solid_info = []
    for i, solid in enumerate(shape.Solids()):
        sb = solid.BoundingBox()
        solid_info.append((solid.Volume(), i, sb))
    solid_info.sort(reverse=True, key=lambda item: item[0])
    print('--- SOLIDS BY VOLUME ---')
    for volume, i, sb in solid_info:
        print('SOLID %02d vol=%.3f bbox x[%.2f,%.2f] y[%.2f,%.2f] z[%.2f,%.2f]' % (
            i, volume, sb.xmin, sb.xmax, sb.ymin, sb.ymax, sb.zmin, sb.zmax))

    rear_threshold = bbox.ymax - max(40.0, bbox.ylen * 0.20)
    face_info = []
    for i, face in enumerate(shape.Faces()):
        fb = face.BoundingBox()
        if fb.ymax >= rear_threshold:
            try:
                area = face.Area()
            except Exception:
                area = 0.0
            try:
                kind = face.geomType()
            except Exception:
                kind = 'UNKNOWN'
            c = face.Center()
            face_info.append((area, i, kind, c, fb))
    face_info.sort(reverse=True, key=lambda item: item[0])
    print('--- LARGEST FACES NEAR POSITIVE-Y REAR ---')
    for area, i, kind, c, fb in face_info[:60]:
        print('FACE %03d type=%s area=%.3f center=(%.2f,%.2f,%.2f) bbox x[%.2f,%.2f] y[%.2f,%.2f] z[%.2f,%.2f]' % (
            i, kind, area, c.x, c.y, c.z,
            fb.xmin, fb.xmax, fb.ymin, fb.ymax, fb.zmin, fb.zmax))
    return model