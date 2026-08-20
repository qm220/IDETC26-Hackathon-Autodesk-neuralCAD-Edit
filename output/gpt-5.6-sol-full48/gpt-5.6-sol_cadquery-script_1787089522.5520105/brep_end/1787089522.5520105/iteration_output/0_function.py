def my_cad_function(args):
    import os
    input_file = os.path.expanduser(args['input_file'])
    model = cq.importers.importStep(input_file)
    shape = model.val()
    bbox = shape.BoundingBox()
    print('MODEL VALID:', shape.isValid())
    print('MODEL TYPE:', shape.ShapeType())
    print('MODEL BBOX: x=[%.3f, %.3f] y=[%.3f, %.3f] z=[%.3f, %.3f]' % (bbox.xmin, bbox.xmax, bbox.ymin, bbox.ymax, bbox.zmin, bbox.zmax))
    print('MODEL SIZE: x=%.3f y=%.3f z=%.3f' % (bbox.xlen, bbox.ylen, bbox.zlen))

    solids = shape.Solids()
    print('SOLID COUNT:', len(solids))
    solid_data = []
    for index, solid in enumerate(solids):
        sb = solid.BoundingBox()
        solid_data.append((solid.Volume(), index, sb))
    solid_data.sort(key=lambda item: item[0], reverse=True)
    for rank, (volume, index, sb) in enumerate(solid_data[:40]):
        print('SOLID rank=%d index=%d volume=%.3f bbox x=[%.3f,%.3f] y=[%.3f,%.3f] z=[%.3f,%.3f]' % (rank, index, volume, sb.xmin, sb.xmax, sb.ymin, sb.ymax, sb.zmin, sb.zmax))

    rear_faces = []
    for index, face in enumerate(shape.Faces()):
        try:
            fb = face.BoundingBox()
            center = face.Center()
            normal = face.normalAt(center)
            if normal.y < -0.80:
                rear_faces.append((face.Area(), index, center, normal, fb))
        except Exception:
            pass
    rear_faces.sort(key=lambda item: item[0], reverse=True)
    print('REAR-FACING FACE COUNT:', len(rear_faces))
    for rank, (area, index, center, normal, fb) in enumerate(rear_faces[:30]):
        print('REAR FACE rank=%d index=%d area=%.3f center=(%.3f,%.3f,%.3f) normal=(%.3f,%.3f,%.3f) bbox x=[%.3f,%.3f] y=[%.3f,%.3f] z=[%.3f,%.3f]' % (rank, index, area, center.x, center.y, center.z, normal.x, normal.y, normal.z, fb.xmin, fb.xmax, fb.ymin, fb.ymax, fb.zmin, fb.zmax))

    return model
