def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    bb = shape.BoundingBox()
    c = bb.center
    print("MODEL valid=%s volume=%.6f faces=%d solids=%d" % (
        shape.isValid(), shape.Volume(), len(shape.Faces()), len(shape.Solids())))
    print("MODEL bbox=(%.4f,%.4f,%.4f)-(%.4f,%.4f,%.4f) center=(%.4f,%.4f,%.4f)" % (
        bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax,
        c.x, c.y, c.z))

    for si, solid in enumerate(shape.Solids()):
        sb = solid.BoundingBox()
        sc = sb.center
        print("SOLID %d volume=%.6f faces=%d bbox=(%.4f,%.4f,%.4f)-(%.4f,%.4f,%.4f) center=(%.4f,%.4f,%.4f)" % (
            si, solid.Volume(), len(solid.Faces()),
            sb.xmin, sb.ymin, sb.zmin, sb.xmax, sb.ymax, sb.zmax,
            sc.x, sc.y, sc.z))

    # Bind the planned F001 FACE indices to the actual imported STEP geometry.
    faces = shape.Faces()
    for i in range(min(234, len(faces))):
        f = faces[i]
        fc = f.Center()
        fb = f.BoundingBox()
        normal_text = ""
        if f.geomType() == "PLANE":
            try:
                n = f.normalAt()
                normal_text = " n=(%.3f,%.3f,%.3f)" % (n.x, n.y, n.z)
            except Exception:
                pass
        print("FACE %d type=%s area=%.6f center=(%.4f,%.4f,%.4f) bbox=(%.4f,%.4f,%.4f)-(%.4f,%.4f,%.4f)%s" % (
            i, f.geomType(), f.Area(), fc.x, fc.y, fc.z,
            fb.xmin, fb.ymin, fb.zmin, fb.xmax, fb.ymax, fb.zmax,
            normal_text))

    # Also report edge ranges near the model axis to identify the flower-profile
    # envelope, orientation, and through-depth for the next modeling iteration.
    axis_tol = 30.0
    for i, edge in enumerate(shape.Edges()):
        eb = edge.BoundingBox()
        ec = edge.Center()
        if (eb.xmin <= c.x + axis_tol and eb.xmax >= c.x - axis_tol and
                eb.ymin <= c.y + axis_tol and eb.ymax >= c.y - axis_tol):
            print("CENTER_EDGE %d type=%s length=%.6f center=(%.4f,%.4f,%.4f) bbox=(%.4f,%.4f,%.4f)-(%.4f,%.4f,%.4f)" % (
                i, edge.geomType(), edge.Length(), ec.x, ec.y, ec.z,
                eb.xmin, eb.ymin, eb.zmin, eb.xmax, eb.ymax, eb.zmax))

    return model