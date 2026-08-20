def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    bb = shape.BoundingBox()
    print("MODEL bbox: x=[%.3f, %.3f] y=[%.3f, %.3f] z=[%.3f, %.3f]" %
          (bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax))
    print("MODEL solids=%d faces=%d valid=%s" %
          (len(shape.Solids()), len(shape.Faces()), shape.isValid()))

    faces = shape.Faces()
    target_indices = list(range(402, 425))
    print("--- Candidate control/button faces ---")
    for i in target_indices:
        if i >= len(faces):
            continue
        face = faces[i]
        c = face.Center()
        fb = face.BoundingBox()
        try:
            geom = face.geomType()
        except Exception:
            geom = "UNKNOWN"
        try:
            normal = face.normalAt(c)
            normal_text = "(%.4f, %.4f, %.4f)" % (normal.x, normal.y, normal.z)
        except Exception:
            normal_text = "n/a"
        print("FACE %d type=%s area=%.4f center=(%.3f, %.3f, %.3f) normal=%s bbox=x[%.3f,%.3f] y[%.3f,%.3f] z[%.3f,%.3f]" %
              (i, geom, face.Area(), c.x, c.y, c.z, normal_text,
               fb.xmin, fb.xmax, fb.ymin, fb.ymax, fb.zmin, fb.zmax))

    print("--- Solids ---")
    for i, solid in enumerate(shape.Solids()):
        sb = solid.BoundingBox()
        sc = solid.Center()
        global_face_ids = []
        for local_face in solid.Faces():
            for gi, global_face in enumerate(faces):
                try:
                    if local_face.isSame(global_face):
                        global_face_ids.append(gi)
                        break
                except Exception:
                    pass
        print("SOLID %d volume=%.3f center=(%.3f, %.3f, %.3f) bbox=x[%.3f,%.3f] y[%.3f,%.3f] z[%.3f,%.3f] faces=%s" %
              (i, solid.Volume(), sc.x, sc.y, sc.z,
               sb.xmin, sb.xmax, sb.ymin, sb.ymax, sb.zmin, sb.zmax,
               global_face_ids))

    return model