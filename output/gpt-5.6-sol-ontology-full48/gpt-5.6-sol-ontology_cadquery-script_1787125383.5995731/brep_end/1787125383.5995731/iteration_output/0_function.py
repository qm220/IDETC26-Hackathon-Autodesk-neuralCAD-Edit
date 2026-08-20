def my_cad_function(args):
    import os
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    bbox = shape.BoundingBox()
    print("MODEL VALID:", shape.isValid())
    print("SOLIDS:", len(shape.Solids()), "FACES:", len(shape.Faces()), "EDGES:", len(shape.Edges()))
    print("VOLUME:", shape.Volume())
    print("BBOX:", (bbox.xmin, bbox.ymin, bbox.zmin), (bbox.xmax, bbox.ymax, bbox.zmax))

    print("--- FACE INSPECTION (CadQuery/OCC list order) ---")
    for i, face in enumerate(shape.Faces()):
        bb = face.BoundingBox()
        c = face.Center()
        try:
            geom_type = face.geomType()
        except Exception:
            geom_type = "UNKNOWN"
        try:
            n = face.normalAt(c)
            normal_text = "(%.6f, %.6f, %.6f)" % (n.x, n.y, n.z)
        except Exception:
            normal_text = "unavailable"
        print(
            "FACE %d type=%s area=%.6f center=(%.6f,%.6f,%.6f) "
            "bbox=(%.6f..%.6f, %.6f..%.6f, %.6f..%.6f) normal=%s"
            % (i, geom_type, face.Area(), c.x, c.y, c.z,
               bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax,
               normal_text)
        )

    print("--- EDGE INSPECTION ---")
    for i, edge in enumerate(shape.Edges()):
        bb = edge.BoundingBox()
        c = edge.Center()
        try:
            geom_type = edge.geomType()
        except Exception:
            geom_type = "UNKNOWN"
        print(
            "EDGE %d type=%s length=%.6f center=(%.6f,%.6f,%.6f) "
            "bbox=(%.6f..%.6f, %.6f..%.6f, %.6f..%.6f)"
            % (i, geom_type, edge.Length(), c.x, c.y, c.z,
               bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax)
        )

    return model
