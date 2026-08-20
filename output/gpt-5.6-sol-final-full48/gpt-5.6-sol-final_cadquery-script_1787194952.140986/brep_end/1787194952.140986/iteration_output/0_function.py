def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    print("MODEL VALID:", shape.isValid())
    bb = shape.BoundingBox()
    print("MODEL BBOX:", bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax)

    solids = shape.Solids()
    print("SOLID COUNT:", len(solids))
    for si, solid in enumerate(solids):
        sbb = solid.BoundingBox()
        print("SOLID", si, "volume", solid.Volume(), "bbox", (sbb.xmin, sbb.xmax, sbb.ymin, sbb.ymax, sbb.zmin, sbb.zmax), "faces", len(solid.Faces()))

        for fi, face in enumerate(solid.Faces()):
            c = face.Center()
            fbb = face.BoundingBox()
            radial = (c.x * c.x + c.y * c.y) ** 0.5
            # Report faces in the central 25 mm radius and all planar/conical/cylindrical
            # faces close to either axial side. This identifies the exact front-center
            # transition without relying on unstable imported STEP face indices.
            if radial < 25.0 and max(abs(fbb.xmin), abs(fbb.xmax), abs(fbb.ymin), abs(fbb.ymax)) < 35.0:
                try:
                    gt = face.geomType()
                except Exception:
                    gt = "UNKNOWN"
                try:
                    area = face.Area()
                except Exception:
                    area = -1
                print("CENTER_FACE", si, fi, gt, "area", round(area, 5), "center", (round(c.x, 5), round(c.y, 5), round(c.z, 5)), "bbox", tuple(round(v, 5) for v in (fbb.xmin, fbb.xmax, fbb.ymin, fbb.ymax, fbb.zmin, fbb.zmax)))

        for ei, edge in enumerate(solid.Edges()):
            ebb = edge.BoundingBox()
            ec = edge.Center()
            maxr = max((ebb.xmin**2 + ebb.ymin**2)**0.5,
                       (ebb.xmin**2 + ebb.ymax**2)**0.5,
                       (ebb.xmax**2 + ebb.ymin**2)**0.5,
                       (ebb.xmax**2 + ebb.ymax**2)**0.5)
            if maxr < 25.0:
                try:
                    gt = edge.geomType()
                except Exception:
                    gt = "UNKNOWN"
                print("CENTER_EDGE", si, ei, gt, "len", round(edge.Length(), 5), "center", (round(ec.x, 5), round(ec.y, 5), round(ec.z, 5)), "bbox", tuple(round(v, 5) for v in (ebb.xmin, ebb.xmax, ebb.ymin, ebb.ymax, ebb.zmin, ebb.zmax)))

    return model