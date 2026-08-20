def my_cad_function(args):
    import os
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    bbox = shape.BoundingBox()
    c = bbox.center
    print("MODEL VALID:", shape.isValid())
    print("MODEL VOLUME: %.6f mm^3" % shape.Volume())
    print("MODEL BBOX: x=[%.4f, %.4f], y=[%.4f, %.4f], z=[%.4f, %.4f]" % (
        bbox.xmin, bbox.xmax, bbox.ymin, bbox.ymax, bbox.zmin, bbox.zmax))
    print("MODEL CENTER: (%.4f, %.4f, %.4f)" % (c.x, c.y, c.z))

    faces = shape.Faces()
    print("FACE COUNT:", len(faces))
    for i, face in enumerate(faces):
        fb = face.BoundingBox()
        fc = face.Center()
        try:
            geom_type = face.geomType()
        except Exception:
            geom_type = "UNKNOWN"
        try:
            normal = face.normalAt(fc)
            normal_text = "(%.4f, %.4f, %.4f)" % (normal.x, normal.y, normal.z)
        except Exception:
            normal_text = "N/A"
        print("FACE %d: type=%s area=%.5f center=(%.4f, %.4f, %.4f) normal=%s bbox=[x %.4f..%.4f, y %.4f..%.4f, z %.4f..%.4f]" % (
            i, geom_type, face.Area(), fc.x, fc.y, fc.z, normal_text,
            fb.xmin, fb.xmax, fb.ymin, fb.ymax, fb.zmin, fb.zmax))

    for idx in (26, 31, 32, 34):
        if idx < len(faces):
            face = faces[idx]
            print("GROUNDED FACE %d vertices:" % idx)
            for vertex in face.Vertices():
                p = vertex.Center()
                print("  (%.4f, %.4f, %.4f)" % (p.x, p.y, p.z))

    return model