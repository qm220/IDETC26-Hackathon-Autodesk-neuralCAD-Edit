def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    bb = shape.BoundingBox()
    c = bb.center
    print("VALID", shape.isValid())
    print("VOLUME %.6f" % shape.Volume())
    print("BBOX min=(%.6f, %.6f, %.6f) max=(%.6f, %.6f, %.6f) size=(%.6f, %.6f, %.6f) center=(%.6f, %.6f, %.6f)" % (
        bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax,
        bb.xlen, bb.ylen, bb.zlen, c.x, c.y, c.z))
    print("COUNTS solids=%d faces=%d edges=%d" % (
        len(shape.Solids()), len(shape.Faces()), len(shape.Edges())))

    print("FACE DATA")
    for i, face in enumerate(shape.Faces()):
        fc = face.Center()
        fbb = face.BoundingBox()
        gtype = face.geomType()
        radius = None
        try:
            radius = face.radius()
        except Exception:
            pass
        normal_text = ""
        if gtype == "PLANE":
            try:
                n = face.normalAt()
                normal_text = " n=(%.4f,%.4f,%.4f)" % (n.x, n.y, n.z)
            except Exception:
                pass
        rtext = " r=%.6f" % radius if radius is not None else ""
        print("F%02d type=%s area=%.6f center=(%.4f,%.4f,%.4f) span=(%.4f,%.4f,%.4f)%s%s" % (
            i, gtype, face.Area(), fc.x, fc.y, fc.z,
            fbb.xlen, fbb.ylen, fbb.zlen, rtext, normal_text))

    radiused_edges = []
    for i, edge in enumerate(shape.Edges()):
        etype = edge.geomType()
        if etype in ("CIRCLE", "ELLIPSE"):
            ec = edge.Center()
            try:
                rad = edge.radius()
            except Exception:
                rad = -1.0
            radiused_edges.append((i, etype, rad, edge.Length(), ec.x, ec.y, ec.z))
    print("CURVED EDGE DATA")
    for row in radiused_edges:
        print("E%02d type=%s r=%.6f length=%.6f center=(%.4f,%.4f,%.4f)" % row)

    return model