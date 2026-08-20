def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    print("MODEL VALID:", shape.isValid())
    print("MODEL VOLUME:", shape.Volume())
    print("FACE COUNT:", len(shape.Faces()))
    print("SOLID COUNT:", len(shape.Solids()))

    for i, solid in enumerate(shape.Solids()):
        bb = solid.BoundingBox()
        c = solid.Center()
        print(
            "SOLID %d volume=%.6f center=(%.6f,%.6f,%.6f) "
            "bbox=(%.6f,%.6f,%.6f)-(%.6f,%.6f,%.6f) faces=%d"
            % (i, solid.Volume(), c.x, c.y, c.z,
               bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax,
               len(solid.Faces()))
        )

    target_ids = set([
        12, 24, 25, 26, 27,
        142, 154, 155, 156, 157,
        171, 183, 184, 185, 186,
        200, 212, 213, 214, 215
    ])

    faces = shape.Faces()
    for i, face in enumerate(faces):
        if i not in target_ids:
            continue
        c = face.Center()
        bb = face.BoundingBox()
        gt = face.geomType()
        details = ""
        try:
            if gt == "CYLINDER":
                surf = face._geomAdaptor()
                cyl = surf.Cylinder()
                loc = cyl.Location()
                axis = cyl.Axis().Direction()
                details = " radius=%.6f axis_origin=(%.6f,%.6f,%.6f) axis=(%.6f,%.6f,%.6f)" % (
                    cyl.Radius(), loc.X(), loc.Y(), loc.Z(),
                    axis.X(), axis.Y(), axis.Z())
            elif gt == "PLANE":
                n = face.normalAt(c)
                details = " normal=(%.6f,%.6f,%.6f)" % (n.x, n.y, n.z)
        except Exception as exc:
            details = " detail_error=%s" % exc

        owners = []
        for si, solid in enumerate(shape.Solids()):
            try:
                if any(face.isSame(sf) for sf in solid.Faces()):
                    owners.append(si)
            except Exception:
                pass

        print(
            "FACE %d type=%s area=%.6f center=(%.6f,%.6f,%.6f) "
            "bbox=(%.6f,%.6f,%.6f)-(%.6f,%.6f,%.6f) owners=%s%s"
            % (i, gt, face.Area(), c.x, c.y, c.z,
               bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax,
               owners, details)
        )

    # Also report all cylindrical faces on the four grounded link-plate solids.
    link_solid_ids = [0, 8, 9, 10]
    for si in link_solid_ids:
        solid = shape.Solids()[si]
        print("LINK SOLID", si)
        for fi, face in enumerate(faces):
            try:
                owned = any(face.isSame(sf) for sf in solid.Faces())
            except Exception:
                owned = False
            if not owned or face.geomType() != "CYLINDER":
                continue
            c = face.Center()
            try:
                cyl = face._geomAdaptor().Cylinder()
                axis = cyl.Axis().Direction()
                print("  GLOBAL FACE %d cylinder radius=%.6f center=(%.6f,%.6f,%.6f) axis=(%.6f,%.6f,%.6f)" % (
                    fi, cyl.Radius(), c.x, c.y, c.z,
                    axis.X(), axis.Y(), axis.Z()))
            except Exception as exc:
                print("  GLOBAL FACE %d cylinder center=(%.6f,%.6f,%.6f) error=%s" % (
                    fi, c.x, c.y, c.z, exc))

    return model