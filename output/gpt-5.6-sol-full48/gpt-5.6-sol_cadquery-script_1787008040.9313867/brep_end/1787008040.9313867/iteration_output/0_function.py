def my_cad_function(args):
    import os
    shape = cq.importers.importStep(os.path.expanduser(args["input_file"]))
    solid = shape.val()
    bbox = solid.BoundingBox()
    print("VALID", solid.isValid())
    print("VOLUME", solid.Volume())
    print("BBOX", bbox.xmin, bbox.xmax, bbox.ymin, bbox.ymax, bbox.zmin, bbox.zmax)
    print("CENTER", bbox.center.x, bbox.center.y, bbox.center.z)
    print("FACES", len(solid.Faces()), "EDGES", len(solid.Edges()))
    for i, face in enumerate(solid.Faces()):
        c = face.Center()
        try:
            n = face.normalAt(c)
            normal_text = "%.6f %.6f %.6f" % (n.x, n.y, n.z)
        except Exception:
            normal_text = "NA"
        try:
            geom = face.geomType()
        except Exception:
            geom = "NA"
        print("FACE", i, "TYPE", geom, "AREA", round(face.Area(), 5),
              "CENTER", round(c.x, 5), round(c.y, 5), round(c.z, 5),
              "NORMAL", normal_text)
    return shape