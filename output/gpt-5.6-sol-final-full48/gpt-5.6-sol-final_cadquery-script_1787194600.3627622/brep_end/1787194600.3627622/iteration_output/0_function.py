def my_cad_function(args):
    import os
    shape = cq.importers.importStep(os.path.expanduser(args["input_file"]))
    solid = shape.val()
    bb = solid.BoundingBox()
    print("VALID", solid.isValid(), "VOLUME", solid.Volume())
    print("BBOX", (bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax))
    print("CENTER", (bb.center.x, bb.center.y, bb.center.z))

    faces = solid.Faces()
    print("FACE_COUNT", len(faces))
    wanted = set([44,46,49,50,51,52,68,69,74,75,77,78,79,89,90,91,92,99,101,102,103,104,107,178,218,223])
    for i, face in enumerate(faces):
        if i not in wanted:
            continue
        try:
            c = face.Center()
            fbb = face.BoundingBox()
            info = ["FACE", i, face.geomType(), "CENTER", (round(c.x,4),round(c.y,4),round(c.z,4)),
                    "BBOX", (round(fbb.xmin,4),round(fbb.xmax,4),round(fbb.ymin,4),round(fbb.ymax,4),round(fbb.zmin,4),round(fbb.zmax,4)),
                    "AREA", round(face.Area(),4)]
            if face.geomType() == "PLANE":
                n = face.normalAt()
                info += ["NORMAL", (round(n.x,4),round(n.y,4),round(n.z,4))]
            elif face.geomType() == "CYLINDER":
                try:
                    cyl = face._geomAdaptor().Cylinder()
                    ax = cyl.Axis().Direction()
                    loc = cyl.Axis().Location()
                    info += ["RADIUS", round(cyl.Radius(),4), "AXIS", (round(ax.X(),4),round(ax.Y(),4),round(ax.Z(),4)), "LOC", (round(loc.X(),4),round(loc.Y(),4),round(loc.Z(),4))]
                except Exception as e:
                    info += ["CYLINDER_INFO_ERROR", str(e)]
            print(*info)
        except Exception as e:
            print("FACE_ERROR", i, str(e))
    return shape