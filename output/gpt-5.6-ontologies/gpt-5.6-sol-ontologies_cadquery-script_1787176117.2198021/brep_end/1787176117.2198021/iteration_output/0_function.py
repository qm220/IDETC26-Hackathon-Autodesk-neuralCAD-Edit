def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    bbox = shape.BoundingBox()
    print("MODEL VALID:", shape.isValid())
    print("SOLIDS:", len(shape.Solids()), "FACES:", len(shape.Faces()), "EDGES:", len(shape.Edges()))
    print("VOLUME: %.6f" % shape.Volume())
    print("BBOX: xmin=%.4f xmax=%.4f ymin=%.4f ymax=%.4f zmin=%.4f zmax=%.4f" %
          (bbox.xmin, bbox.xmax, bbox.ymin, bbox.ymax, bbox.zmin, bbox.zmax))

    # Bind the planned FACE N identifiers to the imported STEP topology and
    # report geometric data needed to place the hook lock.
    for i, face in enumerate(shape.Faces()):
        c = face.Center()
        fb = face.BoundingBox()
        try:
            geom_type = face.geomType()
        except Exception:
            geom_type = "UNKNOWN"
        try:
            n = face.normalAt(c)
            normal_text = "(%.4f, %.4f, %.4f)" % (n.x, n.y, n.z)
        except Exception:
            normal_text = "n/a"
        print("FACE %d type=%s area=%.5f center=(%.4f, %.4f, %.4f) normal=%s bbox=[%.4f,%.4f]x[%.4f,%.4f]x[%.4f,%.4f] edges=%d" %
              (i, geom_type, face.Area(), c.x, c.y, c.z, normal_text,
               fb.xmin, fb.xmax, fb.ymin, fb.ymax, fb.zmin, fb.zmax,
               len(face.Edges())))

    # Extra topology detail for the grounded hook faces F004/F005.
    hook_face_ids = [7, 8, 10, 12, 13, 14, 17]
    faces = shape.Faces()
    for face_id in hook_face_ids:
        if face_id >= len(faces):
            continue
        print("HOOK FACE %d EDGES:" % face_id)
        for j, edge in enumerate(faces[face_id].Edges()):
            ec = edge.Center()
            eb = edge.BoundingBox()
            try:
                et = edge.geomType()
            except Exception:
                et = "UNKNOWN"
            print("  EDGE %d type=%s length=%.5f center=(%.4f, %.4f, %.4f) bbox=[%.4f,%.4f]x[%.4f,%.4f]x[%.4f,%.4f]" %
                  (j, et, edge.Length(), ec.x, ec.y, ec.z,
                   eb.xmin, eb.xmax, eb.ymin, eb.ymax, eb.zmin, eb.zmax))

    return model