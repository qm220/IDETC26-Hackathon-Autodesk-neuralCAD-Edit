def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    solids = imported.solids().vals()
    if len(solids) != 1:
        raise ValueError("Expected one input solid, found %d" % len(solids))

    source = solids[0]
    if not source.isValid():
        raise ValueError("Imported STEP solid is invalid")

    faces = list(source.Faces())
    edges = list(source.Edges())
    print("SOURCE FACES:", len(faces))
    print("SOURCE EDGES:", len(edges))
    print("SOURCE VOLUME: %.9f" % source.Volume())

    # Rebind planning FACE indices to the imported STEP geometry.
    for i, face in enumerate(faces):
        c = face.Center()
        bb = face.BoundingBox()
        print(
            "FACE %d type=%s center=(%.6f,%.6f,%.6f) "
            "bbox=(%.6f,%.6f,%.6f)-(%.6f,%.6f,%.6f)"
            % (i, face.geomType(), c.x, c.y, c.z,
               bb.xmin, bb.ymin, bb.zmin,
               bb.xmax, bb.ymax, bb.zmax)
        )

    def acceptable(shape):
        return (
            shape is not None
            and shape.isValid()
            and len(shape.Solids()) == 1
            and shape.Volume() > 1.0e-8
        )

    # Literal requested operation: apply R=0.2 mm to the complete original
    # edge collection in one fillet feature.
    try:
        exact = source.fillet(0.2, edges)
        if acceptable(exact):
            print("EXACT ALL-EDGE FILLET SUCCEEDED")
            print("FILLETED ORIGINAL EDGES: %d / %d" % (len(edges), len(edges)))
            print("FILLET RADIUS: 0.200000 mm")
            print("RESULT FACES:", len(exact.Faces()))
            print("RESULT EDGES:", len(exact.Edges()))
            print("RESULT VOLUME: %.9f" % exact.Volume())
            return cq.Workplane(obj=exact)
    except Exception as exc:
        print("EXACT R=0.2 ALL-EDGE FILLET FAILED:", repr(exc))

    # Several source walls are exactly 0.2 mm thick. R=0.2 rounds applied to
    # both boundaries necessarily overlap; even R=0.1 makes opposing rounds
    # tangent. Retain the all-edge constraint and find the closest robust
    # constructible radius immediately below that geometric limit.
    trial_radii = [
        0.0999, 0.0995, 0.0990, 0.0980, 0.0970,
        0.0960, 0.0950, 0.0940, 0.0930, 0.0920,
        0.0910, 0.0900, 0.0850, 0.0800, 0.0700,
        0.0600, 0.0500, 0.0400, 0.0300, 0.0200,
        0.0100
    ]

    result = None
    used_radius = None
    for radius in trial_radii:
        try:
            candidate = source.fillet(radius, edges)
            if acceptable(candidate):
                result = candidate
                used_radius = radius
                print("ALL-EDGE FILLET SUCCEEDED AT R=%.6f mm" % radius)
                break
        except Exception as exc:
            print("ALL-EDGE R=%.6f FAILED: %r" % (radius, exc))

    if result is None:
        raise RuntimeError(
            "Unable to construct a valid fillet on every original edge, "
            "including at R=0.01 mm"
        )

    print("FILLETED ORIGINAL EDGES: %d / %d" % (len(edges), len(edges)))
    print("REQUESTED RADIUS: 0.200000 mm")
    print("CONSTRUCTED ALL-EDGE RADIUS: %.6f mm" % used_radius)
    print("RESULT FACES:", len(result.Faces()))
    print("RESULT EDGES:", len(result.Edges()))
    print("RESULT VOLUME: %.9f" % result.Volume())
    return cq.Workplane(obj=result)
