def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    bb = shape.BoundingBox()
    print("MODEL VALID:", shape.isValid())
    print("SOLIDS:", len(shape.Solids()), "FACES:", len(shape.Faces()), "EDGES:", len(shape.Edges()))
    print("VOLUME: %.6f" % shape.Volume())
    print("BBOX: x=(%.4f, %.4f) y=(%.4f, %.4f) z=(%.4f, %.4f)" %
          (bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax))

    faces = shape.Faces()
    relevant = list(range(40, 108))
    for i in relevant:
        if i >= len(faces):
            continue
        f = faces[i]
        c = f.Center()
        fb = f.BoundingBox()
        try:
            gt = f.geomType()
        except Exception:
            gt = "UNKNOWN"
        try:
            n = f.normalAt()
            normal_text = "(%.4f,%.4f,%.4f)" % (n.x, n.y, n.z)
        except Exception:
            normal_text = "n/a"
        print("FACE %d type=%s area=%.4f center=(%.4f,%.4f,%.4f) normal=%s bbox=[%.4f,%.4f; %.4f,%.4f; %.4f,%.4f] edges=%d" %
              (i, gt, f.Area(), c.x, c.y, c.z, normal_text,
               fb.xmin, fb.xmax, fb.ymin, fb.ymax, fb.zmin, fb.zmax,
               len(f.Edges())))

    print("PLANAR FACE SUMMARY:")
    for i, f in enumerate(faces):
        try:
            if f.geomType() != "PLANE":
                continue
            c = f.Center()
            n = f.normalAt()
            fb = f.BoundingBox()
            if f.Area() > 20.0:
                print("PLANE %d area=%.3f c=(%.3f,%.3f,%.3f) n=(%.3f,%.3f,%.3f) size=(%.3f,%.3f,%.3f)" %
                      (i, f.Area(), c.x, c.y, c.z, n.x, n.y, n.z,
                       fb.xlen, fb.ylen, fb.zlen))
        except Exception:
            pass

    return model