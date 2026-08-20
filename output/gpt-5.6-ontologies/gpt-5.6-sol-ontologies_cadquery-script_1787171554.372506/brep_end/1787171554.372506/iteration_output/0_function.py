def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    bbox = shape.BoundingBox()
    print("MODEL VALID:", shape.isValid())
    print("MODEL VOLUME:", shape.Volume())
    print("MODEL BBOX:", (bbox.xmin, bbox.ymin, bbox.zmin), (bbox.xmax, bbox.ymax, bbox.zmax))
    print("MODEL CENTER:", (bbox.center.x, bbox.center.y, bbox.center.z))
    print("FACE COUNT:", len(shape.Faces()))

    for index, face in enumerate(shape.Faces()):
        center = face.Center()
        fb = face.BoundingBox()
        try:
            geom_type = face.geomType()
        except Exception:
            geom_type = "UNKNOWN"
        try:
            normal = face.normalAt(center)
            normal_tuple = (normal.x, normal.y, normal.z)
        except Exception:
            normal_tuple = None
        print(
            "FACE", index,
            "TYPE", geom_type,
            "CENTER", (round(center.x, 5), round(center.y, 5), round(center.z, 5)),
            "NORMAL", normal_tuple,
            "AREA", round(face.Area(), 5),
            "BBOX", (
                round(fb.xmin, 5), round(fb.ymin, 5), round(fb.zmin, 5),
                round(fb.xmax, 5), round(fb.ymax, 5), round(fb.zmax, 5)
            )
        )

    return model