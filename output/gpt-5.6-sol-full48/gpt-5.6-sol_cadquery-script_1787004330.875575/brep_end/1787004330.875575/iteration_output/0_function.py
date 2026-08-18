def my_cad_function(args):
    import os
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    bbox = shape.BoundingBox()
    print("MODEL VALID:", shape.isValid())
    print("MODEL BBOX: x=(%.3f, %.3f), y=(%.3f, %.3f), z=(%.3f, %.3f)" %
          (bbox.xmin, bbox.xmax, bbox.ymin, bbox.ymax, bbox.zmin, bbox.zmax))
    print("MODEL SIZE: x=%.3f, y=%.3f, z=%.3f" % (bbox.xlen, bbox.ylen, bbox.zlen))

    solids = shape.Solids()
    print("SOLID COUNT:", len(solids))
    for index, solid in enumerate(solids):
        sb = solid.BoundingBox()
        sc = solid.Center()
        print("SOLID %02d volume=%.3f center=(%.3f,%.3f,%.3f) bbox=[x %.3f..%.3f, y %.3f..%.3f, z %.3f..%.3f] faces=%d" %
              (index, solid.Volume(), sc.x, sc.y, sc.z,
               sb.xmin, sb.xmax, sb.ymin, sb.ymax, sb.zmin, sb.zmax,
               len(solid.Faces())))

    planar = []
    for fi, face in enumerate(shape.Faces()):
        try:
            geom_type = face.geomType()
            if geom_type == "PLANE":
                area = face.Area()
                center = face.Center()
                normal = face.normalAt(center)
                planar.append((area, fi, center, normal))
        except Exception:
            pass

    planar.sort(key=lambda item: item[0], reverse=True)
    print("LARGEST PLANAR FACES:")
    for area, fi, center, normal in planar[:40]:
        print("FACE_INDEX %03d area=%.3f center=(%.3f,%.3f,%.3f) normal=(%.4f,%.4f,%.4f)" %
              (fi, area, center.x, center.y, center.z,
               normal.x, normal.y, normal.z))

    return model