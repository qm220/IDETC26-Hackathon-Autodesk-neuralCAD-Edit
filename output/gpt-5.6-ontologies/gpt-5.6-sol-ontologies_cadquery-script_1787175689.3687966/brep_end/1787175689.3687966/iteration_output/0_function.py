def my_cad_function(args):
    import os
    from OCP.BRepAdaptor import BRepAdaptor_Surface, BRepAdaptor_Curve
    from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Torus, GeomAbs_Circle

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    bb = shape.BoundingBox()
    print("MODEL valid=%s volume=%.6f faces=%d edges=%d" % (
        shape.isValid(), shape.Volume(), len(shape.Faces()), len(shape.Edges())))
    print("MODEL bbox=(%.6f, %.6f, %.6f) to (%.6f, %.6f, %.6f)" % (
        bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax))

    faces = shape.Faces()
    for i, face in enumerate(faces):
        c = face.Center()
        fbb = face.BoundingBox()
        kind = face.geomType()
        details = ""
        try:
            surf = BRepAdaptor_Surface(face.wrapped, True)
            st = surf.GetType()
            if st == GeomAbs_Cylinder:
                cyl = surf.Cylinder()
                ax = cyl.Axis().Direction()
                details = " radius=%.9f axis=(%.5f,%.5f,%.5f)" % (
                    cyl.Radius(), ax.X(), ax.Y(), ax.Z())
            elif st == GeomAbs_Torus:
                tor = surf.Torus()
                ax = tor.Axis().Direction()
                details = " majorR=%.9f minorR=%.9f axis=(%.5f,%.5f,%.5f)" % (
                    tor.MajorRadius(), tor.MinorRadius(), ax.X(), ax.Y(), ax.Z())
        except Exception as exc:
            details = " adaptor_error=%s" % exc
        print("FACE %d type=%s area=%.9f center=(%.6f,%.6f,%.6f) bbox=(%.6f,%.6f,%.6f)-(%.6f,%.6f,%.6f)%s" % (
            i, kind, face.Area(), c.x, c.y, c.z,
            fbb.xmin, fbb.ymin, fbb.zmin, fbb.xmax, fbb.ymax, fbb.zmax,
            details))

        edge_data = []
        for j, edge in enumerate(face.Edges()):
            ec = edge.Center()
            entry = "e%d:%s L=%.6f C=(%.4f,%.4f,%.4f)" % (
                j, edge.geomType(), edge.Length(), ec.x, ec.y, ec.z)
            try:
                curve = BRepAdaptor_Curve(edge.wrapped)
                if curve.GetType() == GeomAbs_Circle:
                    entry += " R=%.9f" % curve.Circle().Radius()
            except Exception:
                pass
            edge_data.append(entry)
        print("  EDGES " + " | ".join(edge_data))

    return model