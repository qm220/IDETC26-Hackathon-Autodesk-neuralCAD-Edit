def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    bb = shape.BoundingBox()
    print("MODEL VALID:", shape.isValid())
    print("VOLUME:", shape.Volume())
    print("BBOX: x=(%.3f, %.3f) y=(%.3f, %.3f) z=(%.3f, %.3f)" %
          (bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax))
    print("FACE COUNT:", len(shape.Faces()))

    for i, face in enumerate(shape.Faces()):
        c = face.Center()
        fb = face.BoundingBox()
        try:
            geom = face.geomType()
        except Exception:
            geom = "UNKNOWN"
        try:
            area = face.Area()
        except Exception:
            area = -1.0
        normal_text = ""
        if geom == "PLANE":
            try:
                n = face.normalAt(c)
                normal_text = " normal=(%.4f,%.4f,%.4f)" % (n.x, n.y, n.z)
            except Exception:
                pass
        print("FACE %d type=%s area=%.4f center=(%.4f,%.4f,%.4f) bbox=[%.4f,%.4f]x[%.4f,%.4f]x[%.4f,%.4f]%s edges=%d" %
              (i, geom, area, c.x, c.y, c.z,
               fb.xmin, fb.xmax, fb.ymin, fb.ymax, fb.zmin, fb.zmax,
               normal_text, len(face.Edges())))

    # Inspect the grounded planar flange and large-fillet faces in greater detail.
    inspect_ids = [8, 9, 10, 11, 12, 21, 22, 23, 24, 33, 34,
                   35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49]
    faces = shape.Faces()
    for fi in inspect_ids:
        if fi >= len(faces):
            continue
        print("EDGES OF FACE", fi)
        for ei, edge in enumerate(faces[fi].Edges()):
            ec = edge.Center()
            eb = edge.BoundingBox()
            try:
                et = edge.geomType()
            except Exception:
                et = "UNKNOWN"
            try:
                verts = edge.Vertices()
                endpoints = [(round(v.Center().x, 4), round(v.Center().y, 4), round(v.Center().z, 4)) for v in verts]
            except Exception:
                endpoints = []
            print("  edge %d type=%s len=%.4f center=(%.4f,%.4f,%.4f) bbox=[%.4f,%.4f]x[%.4f,%.4f]x[%.4f,%.4f] vertices=%s" %
                  (ei, et, edge.Length(), ec.x, ec.y, ec.z,
                   eb.xmin, eb.xmax, eb.ymin, eb.ymax, eb.zmin, eb.zmax,
                   endpoints))

    return model