def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    bb = shape.BoundingBox()
    print("MODEL valid=%s solids=%d faces=%d volume=%.6f" % (
        shape.isValid(), len(shape.Solids()), len(shape.Faces()), shape.Volume()))
    print("MODEL bbox min=(%.4f, %.4f, %.4f) max=(%.4f, %.4f, %.4f) size=(%.4f, %.4f, %.4f)" % (
        bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax,
        bb.xlen, bb.ylen, bb.zlen))

    faces = shape.Faces()
    for i, face in enumerate(faces):
        kind = face.geomType()
        c = face.Center()
        fb = face.BoundingBox()
        # Print all analytically useful faces and all planning-grounded hole faces.
        if kind in ("PLANE", "CYLINDER") or i in (44, 46, 49, 50, 51, 52):
            extra = ""
            try:
                if kind == "PLANE":
                    n = face.normalAt(c)
                    extra = " normal=(%.4f,%.4f,%.4f)" % (n.x, n.y, n.z)
                elif kind == "CYLINDER":
                    extra = " radius=%.6f" % face._geomAdaptor().Cylinder().Radius()
            except Exception as exc:
                extra = " analytic_info_error=%s" % exc
            print("FACE %d type=%s center=(%.4f,%.4f,%.4f) area=%.5f bbox=[(%.4f,%.4f,%.4f),(%.4f,%.4f,%.4f)]%s" % (
                i, kind, c.x, c.y, c.z, face.Area(),
                fb.xmin, fb.ymin, fb.zmin, fb.xmax, fb.ymax, fb.zmax, extra))

    # Explicitly report the grounded existing bore faces for geometric binding.
    for i in (44, 46, 49, 50, 51, 52):
        if i < len(faces):
            f = faces[i]
            c = f.Center()
            print("GROUNDED FACE %d: type=%s center=(%.6f,%.6f,%.6f)" %
                  (i, f.geomType(), c.x, c.y, c.z))

    return model