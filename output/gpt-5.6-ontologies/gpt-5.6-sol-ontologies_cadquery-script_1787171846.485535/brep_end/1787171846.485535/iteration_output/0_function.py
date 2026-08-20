def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    bbox = shape.BoundingBox()
    print("MODEL BBOX: x=[%.3f, %.3f], y=[%.3f, %.3f], z=[%.3f, %.3f] size=(%.3f, %.3f, %.3f)" % (
        bbox.xmin, bbox.xmax, bbox.ymin, bbox.ymax, bbox.zmin, bbox.zmax,
        bbox.xlen, bbox.ylen, bbox.zlen))
    print("MODEL: valid=%s solids=%d faces=%d volume=%.3f" % (
        shape.isValid(), len(shape.Solids()), len(shape.Faces()), shape.Volume()))

    solids = shape.Solids()
    for i, solid in enumerate(solids):
        sb = solid.BoundingBox()
        c = solid.Center()
        print("SOLID %d: volume=%.3f center=(%.3f,%.3f,%.3f) bbox=x[%.3f,%.3f] y[%.3f,%.3f] z[%.3f,%.3f] faces=%d" % (
            i, solid.Volume(), c.x, c.y, c.z,
            sb.xmin, sb.xmax, sb.ymin, sb.ymax, sb.zmin, sb.zmax,
            len(solid.Faces())))

    # Inspect the grounded R01/F001 faces on SOLID 0. These local face indices
    # are printed with geometric coordinates so subsequent edits can bind to
    # actual imported STEP topology rather than relying only on JSON labels.
    if solids:
        body = solids[0]
        print("--- SOLID 0 / R01 / F001 FACE INSPECTION ---")
        for i, face in enumerate(body.Faces()):
            c = face.Center()
            fb = face.BoundingBox()
            try:
                geom = face.geomType()
            except Exception:
                geom = "UNKNOWN"
            try:
                n = face.normalAt(c)
                normal_text = "(%.3f,%.3f,%.3f)" % (n.x, n.y, n.z)
            except Exception:
                normal_text = "n/a"
            print("FACE %d: type=%s area=%.3f center=(%.3f,%.3f,%.3f) normal=%s bbox=x[%.3f,%.3f] y[%.3f,%.3f] z[%.3f,%.3f]" % (
                i, geom, face.Area(), c.x, c.y, c.z, normal_text,
                fb.xmin, fb.xmax, fb.ymin, fb.ymax, fb.zmin, fb.zmax))

    return model