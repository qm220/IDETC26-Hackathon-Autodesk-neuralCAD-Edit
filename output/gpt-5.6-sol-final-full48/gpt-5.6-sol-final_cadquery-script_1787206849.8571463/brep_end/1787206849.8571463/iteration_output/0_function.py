def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    bbox = shape.BoundingBox()
    print("VALID", shape.isValid())
    print("VOLUME", shape.Volume())
    print("BBOX", bbox.xmin, bbox.xmax, bbox.ymin, bbox.ymax, bbox.zmin, bbox.zmax)
    print("CENTER", bbox.center.x, bbox.center.y, bbox.center.z)
    print("COUNTS faces edges vertices", len(shape.Faces()), len(shape.Edges()), len(shape.Vertices()))

    print("--- FACES ---")
    for i, face in enumerate(shape.Faces()):
        c = face.Center()
        bb = face.BoundingBox()
        try:
            gt = face.geomType()
        except Exception:
            gt = "UNKNOWN"
        try:
            n = face.normalAt(c)
            normal_text = "%.4f %.4f %.4f" % (n.x, n.y, n.z)
        except Exception:
            normal_text = "NA"
        print("FACE", i, gt,
              "area", round(face.Area(), 5),
              "center", round(c.x, 4), round(c.y, 4), round(c.z, 4),
              "normal", normal_text,
              "bounds", round(bb.xmin, 4), round(bb.xmax, 4),
              round(bb.ymin, 4), round(bb.ymax, 4),
              round(bb.zmin, 4), round(bb.zmax, 4))

    print("--- EDGES ---")
    for i, edge in enumerate(shape.Edges()):
        c = edge.Center()
        bb = edge.BoundingBox()
        verts = edge.Vertices()
        endpoints = []
        for v in verts:
            p = v.Center()
            endpoints.append((round(p.x, 4), round(p.y, 4), round(p.z, 4)))
        try:
            gt = edge.geomType()
        except Exception:
            gt = "UNKNOWN"
        try:
            length = edge.Length()
        except Exception:
            length = -1
        print("EDGE", i, gt,
              "length", round(length, 5),
              "center", round(c.x, 4), round(c.y, 4), round(c.z, 4),
              "ends", endpoints,
              "bounds", round(bb.xmin, 4), round(bb.xmax, 4),
              round(bb.ymin, 4), round(bb.ymax, 4),
              round(bb.zmin, 4), round(bb.zmax, 4))

    return model