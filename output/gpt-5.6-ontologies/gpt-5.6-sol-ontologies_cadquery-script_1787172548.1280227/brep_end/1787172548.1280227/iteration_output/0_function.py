def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    bbox = shape.BoundingBox()
    print("MODEL valid=", shape.isValid())
    print("MODEL bbox=({:.3f},{:.3f},{:.3f}) to ({:.3f},{:.3f},{:.3f}) size=({:.3f},{:.3f},{:.3f})".format(
        bbox.xmin, bbox.ymin, bbox.zmin, bbox.xmax, bbox.ymax, bbox.zmax,
        bbox.xlen, bbox.ylen, bbox.zlen))
    print("MODEL solids={} faces={} volume={:.3f}".format(
        len(shape.Solids()), len(shape.Faces()), shape.Volume()))

    # Identify the analyzed STEP solids by their actual geometry and coordinates.
    for i, solid in enumerate(shape.Solids()):
        sb = solid.BoundingBox()
        c = solid.Center()
        print("SOLID {} vol={:.3f} center=({:.3f},{:.3f},{:.3f}) bbox=({:.3f},{:.3f},{:.3f})-({:.3f},{:.3f},{:.3f}) size=({:.3f},{:.3f},{:.3f}) faces={}".format(
            i, solid.Volume(), c.x, c.y, c.z,
            sb.xmin, sb.ymin, sb.zmin, sb.xmax, sb.ymax, sb.zmax,
            sb.xlen, sb.ylen, sb.zlen, len(solid.Faces())))

    # Bind the FACE N identifiers to the imported topology. Print the largest
    # candidate support faces and all early housing faces with centers/normals.
    faces = shape.Faces()
    records = []
    for i, face in enumerate(faces):
        center = face.Center()
        area = face.Area()
        geom = face.geomType()
        normal = None
        try:
            normal = face.normalAt(center)
        except Exception:
            try:
                normal = face.normalAt()
            except Exception:
                pass
        records.append((area, i, geom, center, normal, face.BoundingBox()))

    print("--- FIRST 80 GLOBAL FACES ---")
    for area, i, geom, center, normal, fb in records[:80]:
        ns = "none" if normal is None else "({:.3f},{:.3f},{:.3f})".format(normal.x, normal.y, normal.z)
        print("FACE {} type={} area={:.3f} center=({:.3f},{:.3f},{:.3f}) normal={} bbox=({:.3f},{:.3f},{:.3f})-({:.3f},{:.3f},{:.3f})".format(
            i, geom, area, center.x, center.y, center.z, ns,
            fb.xmin, fb.ymin, fb.zmin, fb.xmax, fb.ymax, fb.zmax))

    print("--- 40 LARGEST PLANAR FACES ---")
    planar = sorted((r for r in records if r[2] == "PLANE"), reverse=True, key=lambda r: r[0])
    for area, i, geom, center, normal, fb in planar[:40]:
        ns = "none" if normal is None else "({:.3f},{:.3f},{:.3f})".format(normal.x, normal.y, normal.z)
        print("FACE {} area={:.3f} center=({:.3f},{:.3f},{:.3f}) normal={} bbox=({:.3f},{:.3f},{:.3f})-({:.3f},{:.3f},{:.3f})".format(
            i, area, center.x, center.y, center.z, ns,
            fb.xmin, fb.ymin, fb.zmin, fb.xmax, fb.ymax, fb.zmax))

    return model