def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    print("=== Imported STEP inspection ===")
    print("Valid:", shape.isValid())
    print("Compound faces:", len(shape.Faces()))
    print("Compound solids:", len(shape.Solids()))

    solids = list(shape.Solids())
    for si, solid in enumerate(solids):
        bb = solid.BoundingBox()
        c = bb.center
        print(
            "SOLID %d: volume=%.6f bbox=(%.6f, %.6f, %.6f) "
            "center=(%.6f, %.6f, %.6f) faces=%d edges=%d"
            % (si, solid.Volume(), bb.xlen, bb.ylen, bb.zlen,
               c.x, c.y, c.z, len(solid.Faces()), len(solid.Edges()))
        )

    faces = list(shape.Faces())
    target_face_indices = {17, 19, 20, 21}

    print("=== Grounded target faces (global CadQuery indices) ===")
    for fi in sorted(target_face_indices):
        if fi >= len(faces):
            print("FACE %d is out of range" % fi)
            continue
        face = faces[fi]
        bb = face.BoundingBox()
        c = face.Center()
        try:
            gt = face.geomType()
        except Exception:
            gt = "UNKNOWN"
        print(
            "FACE %d: type=%s area=%.6f center=(%.6f, %.6f, %.6f) "
            "bbox=(%.6f, %.6f, %.6f) edges=%d"
            % (fi, gt, face.Area(), c.x, c.y, c.z,
               bb.xlen, bb.ylen, bb.zlen, len(face.Edges()))
        )
        for lei, edge in enumerate(face.Edges()):
            ebb = edge.BoundingBox()
            ec = edge.Center()
            try:
                et = edge.geomType()
            except Exception:
                et = "UNKNOWN"
            try:
                p0 = edge.startPoint()
                p1 = edge.endPoint()
                endpoints = "p0=(%.6f,%.6f,%.6f) p1=(%.6f,%.6f,%.6f)" % (
                    p0.x, p0.y, p0.z, p1.x, p1.y, p1.z)
            except Exception:
                endpoints = "endpoints unavailable"
            adjacent = []
            for afi, aface in enumerate(faces):
                try:
                    if any(edge.isSame(ae) for ae in aface.Edges()):
                        adjacent.append(afi)
                except Exception:
                    pass
            print(
                "  local edge %d: type=%s length=%.6f center=(%.6f,%.6f,%.6f) "
                "bbox=(%.6f,%.6f,%.6f) adjacent_faces=%s %s"
                % (lei, et, edge.Length(), ec.x, ec.y, ec.z,
                   ebb.xlen, ebb.ylen, ebb.zlen, adjacent, endpoints)
            )

    print("=== Long straight edges on each solid ===")
    for si, solid in enumerate(solids):
        for ei, edge in enumerate(solid.Edges()):
            try:
                et = edge.geomType()
            except Exception:
                et = "UNKNOWN"
            if et == "LINE" and edge.Length() > 80.0:
                ec = edge.Center()
                p0 = edge.startPoint()
                p1 = edge.endPoint()
                print(
                    "SOLID %d edge %d: length=%.6f center=(%.6f,%.6f,%.6f) "
                    "p0=(%.6f,%.6f,%.6f) p1=(%.6f,%.6f,%.6f)"
                    % (si, ei, edge.Length(), ec.x, ec.y, ec.z,
                       p0.x, p0.y, p0.z, p1.x, p1.y, p1.z)
                )

    # Inspection-only first iteration: return the original model unchanged.
    return model