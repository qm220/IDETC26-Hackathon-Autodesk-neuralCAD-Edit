def my_cad_function(args):
    import os
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane

    model = cq.importers.importStep(os.path.expanduser(args["input_file"]))
    shape = model.val()
    bbox = shape.BoundingBox()
    print("VALID", shape.isValid())
    print("BBOX", bbox.xmin, bbox.xmax, bbox.ymin, bbox.ymax, bbox.zmin, bbox.zmax)
    print("VOLUME", shape.Volume())

    for index, face in enumerate(shape.Faces()):
        try:
            adaptor = BRepAdaptor_Surface(face.wrapped)
            surface_type = adaptor.GetType()
            center = face.Center()
            fb = face.BoundingBox()
            if surface_type == GeomAbs_Cylinder:
                cylinder = adaptor.Cylinder()
                axis = cylinder.Axis()
                location = axis.Location()
                direction = axis.Direction()
                print(
                    "CYL", index,
                    "R", round(cylinder.Radius(), 6),
                    "AXIS_LOC", round(location.X(), 6), round(location.Y(), 6), round(location.Z(), 6),
                    "AXIS_DIR", round(direction.X(), 6), round(direction.Y(), 6), round(direction.Z(), 6),
                    "CENTER", round(center.x, 6), round(center.y, 6), round(center.z, 6),
                    "FACE_BBOX", round(fb.xmin, 6), round(fb.xmax, 6), round(fb.ymin, 6), round(fb.ymax, 6), round(fb.zmin, 6), round(fb.zmax, 6)
                )
            elif surface_type == GeomAbs_Plane:
                plane = adaptor.Plane()
                axis = plane.Axis()
                direction = axis.Direction()
                print(
                    "PLN", index,
                    "NORMAL", round(direction.X(), 6), round(direction.Y(), 6), round(direction.Z(), 6),
                    "CENTER", round(center.x, 6), round(center.y, 6), round(center.z, 6),
                    "FACE_BBOX", round(fb.xmin, 6), round(fb.xmax, 6), round(fb.ymin, 6), round(fb.ymax, 6), round(fb.zmin, 6), round(fb.zmax, 6)
                )
        except Exception as exc:
            print("FACE_ANALYSIS_ERROR", index, str(exc))

    return model