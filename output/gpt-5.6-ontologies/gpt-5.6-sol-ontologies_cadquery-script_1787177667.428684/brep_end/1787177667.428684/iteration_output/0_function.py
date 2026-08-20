def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    bb = shape.BoundingBox()
    print("MODEL VALID:", shape.isValid())
    print("MODEL BBOX: x=[%.3f, %.3f] y=[%.3f, %.3f] z=[%.3f, %.3f] size=(%.3f, %.3f, %.3f)" % (
        bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax,
        bb.xlen, bb.ylen, bb.zlen))
    print("COUNTS: solids=%d faces=%d" % (len(shape.Solids()), len(shape.Faces())))

    # Inspect component extents to identify the lower rear enclosure solid.
    for i, solid in enumerate(shape.Solids()):
        sb = solid.BoundingBox()
        print("SOLID %d bbox x=[%.3f,%.3f] y=[%.3f,%.3f] z=[%.3f,%.3f] vol=%.3f" % (
            i, sb.xmin, sb.xmax, sb.ymin, sb.ymax, sb.zmin, sb.zmax, solid.Volume()))

    # FACE 398 is the grounded rear-panel face. Inspect it and its neighboring
    # F004 faces before selecting geometry for the cut.
    faces = shape.Faces()
    for i in range(394, min(402, len(faces))):
        face = faces[i]
        fb = face.BoundingBox()
        c = face.Center()
        try:
            n = face.normalAt()
            normal_text = "(%.5f,%.5f,%.5f)" % (n.x, n.y, n.z)
        except Exception as exc:
            normal_text = "unavailable:%s" % exc
        try:
            gtype = face.geomType()
        except Exception:
            gtype = "unknown"
        print("FACE %d type=%s center=(%.3f,%.3f,%.3f) normal=%s area=%.3f bbox=x[%.3f,%.3f] y[%.3f,%.3f] z[%.3f,%.3f]" % (
            i, gtype, c.x, c.y, c.z, normal_text, face.Area(),
            fb.xmin, fb.xmax, fb.ymin, fb.ymax, fb.zmin, fb.zmax))

    return model