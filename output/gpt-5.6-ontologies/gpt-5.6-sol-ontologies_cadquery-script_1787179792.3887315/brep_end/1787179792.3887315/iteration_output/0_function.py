def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    bbox = shape.BoundingBox()
    print("MODEL VALID:", shape.isValid())
    print("VOLUME:", shape.Volume())
    print("BBOX:", (bbox.xmin, bbox.ymin, bbox.zmin), (bbox.xmax, bbox.ymax, bbox.zmax))
    print("FACE COUNT:", len(shape.Faces()), "EDGE COUNT:", len(shape.Edges()))

    for i, face in enumerate(shape.Faces()):
        c = face.Center()
        fb = face.BoundingBox()
        try:
            gt = face.geomType()
        except Exception:
            gt = "UNKNOWN"
        try:
            n = face.normalAt(c)
            normal = (round(n.x, 5), round(n.y, 5), round(n.z, 5))
        except Exception:
            normal = None
        radius = None
        if gt in ("CYLINDER", "SPHERE", "TORUS", "CONE"):
            try:
                adaptor = face._geomAdaptor()
                if gt == "CYLINDER":
                    radius = adaptor.Cylinder().Radius()
                elif gt == "SPHERE":
                    radius = adaptor.Sphere().Radius()
                elif gt == "TORUS":
                    radius = (adaptor.Torus().MajorRadius(), adaptor.Torus().MinorRadius())
                elif gt == "CONE":
                    radius = adaptor.Cone().RefRadius()
            except Exception as exc:
                radius = "unavailable: " + str(exc)
        print(
            "FACE", i,
            "type=", gt,
            "center=", (round(c.x, 5), round(c.y, 5), round(c.z, 5)),
            "normal=", normal,
            "area=", round(face.Area(), 5),
            "radius=", radius,
            "bbox=", (
                round(fb.xmin, 5), round(fb.xmax, 5),
                round(fb.ymin, 5), round(fb.ymax, 5),
                round(fb.zmin, 5), round(fb.zmax, 5)
            ),
            "edges=", len(face.Edges())
        )

    print("--- GLOBAL EDGES ---")
    for i, edge in enumerate(shape.Edges()):
        c = edge.Center()
        eb = edge.BoundingBox()
        try:
            gt = edge.geomType()
        except Exception:
            gt = "UNKNOWN"
        try:
            length = edge.Length()
        except Exception:
            length = -1
        vertices = []
        for vertex in edge.Vertices():
            p = vertex.Center()
            vertices.append((round(p.x, 5), round(p.y, 5), round(p.z, 5)))
        print(
            "EDGE", i,
            "type=", gt,
            "center=", (round(c.x, 5), round(c.y, 5), round(c.z, 5)),
            "length=", round(length, 5),
            "vertices=", vertices,
            "bbox=", (
                round(eb.xmin, 5), round(eb.xmax, 5),
                round(eb.ymin, 5), round(eb.ymax, 5),
                round(eb.zmin, 5), round(eb.zmax, 5)
            )
        )

    return model