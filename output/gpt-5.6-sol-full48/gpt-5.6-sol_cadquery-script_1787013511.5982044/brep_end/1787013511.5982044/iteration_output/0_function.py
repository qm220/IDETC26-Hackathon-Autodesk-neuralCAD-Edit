def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    bb = shape.BoundingBox()
    c = bb.center
    print("VALID", shape.isValid())
    print("VOLUME", round(shape.Volume(), 6))
    print("BBOX", (bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax))
    print("CENTER", (c.x, c.y, c.z))
    print("COUNTS faces/edges/vertices", len(shape.Faces()), len(shape.Edges()), len(shape.Vertices()))

    print("--- FACES ---")
    for i, face in enumerate(shape.Faces()):
        fc = face.Center()
        fbb = face.BoundingBox()
        try:
            gt = face.geomType()
        except Exception:
            gt = "UNKNOWN"
        try:
            area = face.Area()
        except Exception:
            area = -1
        try:
            n = face.normalAt(fc)
            normal = (round(n.x, 4), round(n.y, 4), round(n.z, 4))
        except Exception:
            normal = None
        print("FACE", i, "type", gt, "area", round(area, 3),
              "center", (round(fc.x, 3), round(fc.y, 3), round(fc.z, 3)),
              "normal", normal,
              "bbox", tuple(round(v, 3) for v in (fbb.xmin, fbb.xmax, fbb.ymin, fbb.ymax, fbb.zmin, fbb.zmax)))

    print("--- EDGES ---")
    for i, edge in enumerate(shape.Edges()):
        ec = edge.Center()
        ebb = edge.BoundingBox()
        try:
            gt = edge.geomType()
        except Exception:
            gt = "UNKNOWN"
        try:
            length = edge.Length()
        except Exception:
            length = -1
        radius = None
        if gt == "CIRCLE":
            try:
                radius = edge.radius()
            except Exception:
                try:
                    radius = edge._geomAdaptor().Circle().Radius()
                except Exception:
                    pass
        print("EDGE", i, "type", gt, "length", round(length, 3),
              "radius", None if radius is None else round(radius, 4),
              "center", (round(ec.x, 3), round(ec.y, 3), round(ec.z, 3)),
              "bbox", tuple(round(v, 3) for v in (ebb.xmin, ebb.xmax, ebb.ymin, ebb.ymax, ebb.zmin, ebb.zmax)))

    return model