def my_cad_function(args):
    import os

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    print("Loaded STEP:", input_file)
    print("Valid:", shape.isValid())
    print("Solids:", len(shape.Solids()), "Faces:", len(shape.Faces()))
    bb = shape.BoundingBox()
    print("Model bbox: x=[%.6f, %.6f] y=[%.6f, %.6f] z=[%.6f, %.6f]" %
          (bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax))

    faces = shape.Faces()
    for i, face in enumerate(faces):
        c = face.Center()
        fbb = face.BoundingBox()
        try:
            gt = face.geomType()
        except Exception as exc:
            gt = "UNKNOWN(%s)" % exc
        try:
            area = face.Area()
        except Exception:
            area = -1.0
        print("FACE %d: type=%s center=(%.6f, %.6f, %.6f) area=%.6f bbox=(%.6f,%.6f)x(%.6f,%.6f)x(%.6f,%.6f) edges=%d" %
              (i, gt, c.x, c.y, c.z, area,
               fbb.xmin, fbb.xmax, fbb.ymin, fbb.ymax, fbb.zmin, fbb.zmax,
               len(face.Edges())))

        if i == 21 or gt == "CYLINDER":
            for j, edge in enumerate(face.Edges()):
                ec = edge.Center()
                ebb = edge.BoundingBox()
                try:
                    egt = edge.geomType()
                except Exception as exc:
                    egt = "UNKNOWN(%s)" % exc
                try:
                    radius = edge.radius()
                    radius_text = "%.9f" % radius
                except Exception:
                    radius_text = "n/a"
                try:
                    length = edge.Length()
                except Exception:
                    length = -1.0
                print("  EDGE %d: type=%s center=(%.6f, %.6f, %.6f) length=%.6f radius=%s bbox=(%.6f,%.6f)x(%.6f,%.6f)x(%.6f,%.6f)" %
                      (j, egt, ec.x, ec.y, ec.z, length, radius_text,
                       ebb.xmin, ebb.xmax, ebb.ymin, ebb.ymax, ebb.zmin, ebb.zmax))

    target = faces[21]
    print("Grounded FACE 21 type:", target.geomType())
    print("Returning unedited model for first-iteration geometry inspection.")
    return model