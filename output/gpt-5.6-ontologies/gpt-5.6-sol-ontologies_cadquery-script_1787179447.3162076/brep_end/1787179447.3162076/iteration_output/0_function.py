def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    solids = shape.Solids()
    faces = shape.Faces()
    bb = shape.BoundingBox()
    print("MODEL valid=%s solids=%d faces=%d volume=%.6f" % (
        shape.isValid(), len(solids), len(faces), shape.Volume()))
    print("MODEL bbox=(%.3f, %.3f, %.3f) to (%.3f, %.3f, %.3f)" % (
        bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax))

    # Inspect every assembly body so the likely vessel and handle can be
    # identified geometrically rather than relying on unresolved semantic names.
    for i, solid in enumerate(solids):
        sb = solid.BoundingBox()
        c = solid.Center()
        print("SOLID %d volume=%.6f faces=%d center=(%.3f,%.3f,%.3f) bbox=(%.3f,%.3f,%.3f)-(%.3f,%.3f,%.3f)" % (
            i, solid.Volume(), len(solid.Faces()), c.x, c.y, c.z,
            sb.xmin, sb.ymin, sb.zmin, sb.xmax, sb.ymax, sb.zmax))

    # Report actual positive common volumes between distinct STEP solids. These
    # are candidates for the requested static handle-to-body collision.
    print("PAIRWISE INTERSECTIONS:")
    for i in range(len(solids)):
        bi = solids[i].BoundingBox()
        for j in range(i + 1, len(solids)):
            bj = solids[j].BoundingBox()
            if (bi.xmax < bj.xmin or bj.xmax < bi.xmin or
                bi.ymax < bj.ymin or bj.ymax < bi.ymin or
                bi.zmax < bj.zmin or bj.zmax < bi.zmin):
                continue
            try:
                common = solids[i].intersect(solids[j])
                volume = common.Volume()
                if volume > 1.0e-5:
                    cb = common.BoundingBox()
                    print("INTERSECTION %d-%d volume=%.6f bbox=(%.3f,%.3f,%.3f)-(%.3f,%.3f,%.3f)" % (
                        i, j, volume, cb.xmin, cb.ymin, cb.zmin,
                        cb.xmax, cb.ymax, cb.zmax))
            except Exception as exc:
                print("INTERSECTION_ERROR %d-%d: %s" % (i, j, exc))

    # Bind the planning-stage face indices to the imported STEP geometry.
    print("FACE BINDINGS:")
    for i, face in enumerate(faces):
        c = face.Center()
        fb = face.BoundingBox()
        try:
            geom_type = face.geomType()
        except Exception:
            geom_type = "UNKNOWN"
        print("FACE %d type=%s area=%.6f center=(%.3f,%.3f,%.3f) bbox=(%.3f,%.3f,%.3f)-(%.3f,%.3f,%.3f)" % (
            i, geom_type, face.Area(), c.x, c.y, c.z,
            fb.xmin, fb.ymin, fb.zmin, fb.xmax, fb.ymax, fb.zmax))

    return model