def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    bbox = shape.BoundingBox()
    print("MODEL VALID:", shape.isValid())
    print("SOLIDS:", len(shape.Solids()), "FACES:", len(shape.Faces()), "EDGES:", len(shape.Edges()))
    print("VOLUME: %.6f" % shape.Volume())
    print("BBOX: x=[%.6f, %.6f] y=[%.6f, %.6f] z=[%.6f, %.6f]" % (
        bbox.xmin, bbox.xmax, bbox.ymin, bbox.ymax, bbox.zmin, bbox.zmax))

    # Bind the planning-stage FACE indices to the imported STEP topology.
    for i, face in enumerate(shape.Faces()):
        c = face.Center()
        fb = face.BoundingBox()
        try:
            geom = face.geomType()
        except Exception:
            geom = "UNKNOWN"
        try:
            n = face.normalAt(c)
            normal_text = "(%.5f, %.5f, %.5f)" % (n.x, n.y, n.z)
        except Exception:
            normal_text = "n/a"
        print("FACE %02d type=%-10s area=%12.6f center=(%10.4f,%10.4f,%10.4f) normal=%s bbox=(%.3f,%.3f)x(%.3f,%.3f)x(%.3f,%.3f) edges=%d" % (
            i, geom, face.Area(), c.x, c.y, c.z, normal_text,
            fb.xmin, fb.xmax, fb.ymin, fb.ymax, fb.zmin, fb.zmax,
            len(face.Edges())))

    # Inspect the edges of FACE 34 (mounting land) and the original F005 faces.
    faces = shape.Faces()
    for fi in [34, 35, 36, 37, 38, 39, 40, 41, 42]:
        if fi >= len(faces):
            continue
        print("TARGET FACE", fi, "TYPE", faces[fi].geomType())
        for ei, edge in enumerate(faces[fi].Edges()):
            ec = edge.Center()
            eb = edge.BoundingBox()
            try:
                et = edge.geomType()
            except Exception:
                et = "UNKNOWN"
            print("  EDGE %02d type=%-8s len=%10.5f center=(%9.3f,%9.3f,%9.3f) bbox=(%.3f,%.3f)x(%.3f,%.3f)x(%.3f,%.3f)" % (
                ei, et, edge.Length(), ec.x, ec.y, ec.z,
                eb.xmin, eb.xmax, eb.ymin, eb.ymax, eb.zmin, eb.zmax))

    return model