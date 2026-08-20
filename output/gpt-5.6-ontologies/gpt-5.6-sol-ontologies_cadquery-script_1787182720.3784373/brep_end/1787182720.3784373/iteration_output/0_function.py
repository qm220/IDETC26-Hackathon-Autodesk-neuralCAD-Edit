def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    print("MODEL VALID:", shape.isValid())
    print("GLOBAL FACES:", len(shape.Faces()), "SOLIDS:", len(shape.Solids()))
    bb = shape.BoundingBox()
    print("MODEL BBOX:", (bb.xmin, bb.ymin, bb.zmin), (bb.xmax, bb.ymax, bb.zmax))

    # Inspect every imported solid so the planned F002 face range can be bound
    # to its actual geometry rather than relying only on the STEP ordering.
    for i, solid in enumerate(shape.Solids()):
        sb = solid.BoundingBox()
        sc = solid.Center()
        print("SOLID", i,
              "faces", len(solid.Faces()),
              "volume", round(solid.Volume(), 4),
              "center", tuple(round(v, 4) for v in (sc.x, sc.y, sc.z)),
              "bbox", tuple(round(v, 4) for v in
                            (sb.xmin, sb.ymin, sb.zmin, sb.xmax, sb.ymax, sb.zmax)))

    faces = shape.Faces()
    print("--- F002 FACE INSPECTION (global FACE 266..557) ---")
    for idx in range(266, min(558, len(faces))):
        face = faces[idx]
        kind = face.geomType()
        c = face.Center()
        area = face.Area()
        fb = face.BoundingBox()

        # Report planar faces large enough to be possible rear interfaces and
        # every cylindrical/conical face that may describe an existing hole.
        report = kind in ("CYLINDER", "CONE") or area > 15.0
        if not report:
            continue

        extra = ""
        if kind == "PLANE":
            try:
                n = face.normalAt(c)
                extra = " normal=(%.4f,%.4f,%.4f)" % (n.x, n.y, n.z)
            except Exception as exc:
                extra = " normal-error=" + str(exc)
        elif kind in ("CYLINDER", "CONE"):
            try:
                extra += " radius=%.5f" % face.radius()
            except Exception:
                pass

        print("FACE", idx,
              "type", kind,
              "area", round(area, 5),
              "center", tuple(round(v, 5) for v in (c.x, c.y, c.z)),
              "bbox", tuple(round(v, 5) for v in
                            (fb.xmin, fb.ymin, fb.zmin, fb.xmax, fb.ymax, fb.zmax)),
              extra)

    # First iteration is intentionally diagnostic; preserve and return the
    # source model while collecting coordinates for the grounded edit.
    return model