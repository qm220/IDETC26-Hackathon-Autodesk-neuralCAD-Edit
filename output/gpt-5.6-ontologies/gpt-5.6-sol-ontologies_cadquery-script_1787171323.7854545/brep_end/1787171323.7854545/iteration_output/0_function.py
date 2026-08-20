def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    bbox = shape.BoundingBox()
    print("MODEL VALID:", shape.isValid())
    print("MODEL VOLUME: %.6f" % shape.Volume())
    print("MODEL FACES:", len(shape.Faces()))
    print("MODEL BBOX: x=[%.6f, %.6f] y=[%.6f, %.6f] z=[%.6f, %.6f]" %
          (bbox.xmin, bbox.xmax, bbox.ymin, bbox.ymax, bbox.zmin, bbox.zmax))

    faces = shape.Faces()
    for i, face in enumerate(faces):
        c = face.Center()
        fb = face.BoundingBox()
        try:
            gt = face.geomType()
        except Exception:
            gt = "UNKNOWN"
        try:
            n = face.normalAt(c)
            normal_text = "(%.6f, %.6f, %.6f)" % (n.x, n.y, n.z)
        except Exception:
            normal_text = "unavailable"
        print("FACE %d type=%s area=%.6f center=(%.6f, %.6f, %.6f) normal=%s bbox=[x %.6f..%.6f, y %.6f..%.6f, z %.6f..%.6f] wires=%d edges=%d" %
              (i, gt, face.Area(), c.x, c.y, c.z, normal_text,
               fb.xmin, fb.xmax, fb.ymin, fb.ymax, fb.zmin, fb.zmax,
               len(face.Wires()), len(face.Edges())))

        if 14 <= i <= 23:
            for wi, wire in enumerate(face.Wires()):
                wb = wire.BoundingBox()
                print("  FACE %d WIRE %d length=%.6f bbox=[x %.6f..%.6f, y %.6f..%.6f, z %.6f..%.6f] edges=%d" %
                      (i, wi, wire.Length(), wb.xmin, wb.xmax, wb.ymin, wb.ymax,
                       wb.zmin, wb.zmax, len(wire.Edges())))
            for ei, edge in enumerate(face.Edges()):
                ec = edge.Center()
                eb = edge.BoundingBox()
                try:
                    et = edge.geomType()
                except Exception:
                    et = "UNKNOWN"
                print("  FACE %d EDGE %d type=%s length=%.6f center=(%.6f, %.6f, %.6f) bbox=[x %.6f..%.6f, y %.6f..%.6f, z %.6f..%.6f]" %
                      (i, ei, et, edge.Length(), ec.x, ec.y, ec.z,
                       eb.xmin, eb.xmax, eb.ymin, eb.ymax, eb.zmin, eb.zmax))

    return model