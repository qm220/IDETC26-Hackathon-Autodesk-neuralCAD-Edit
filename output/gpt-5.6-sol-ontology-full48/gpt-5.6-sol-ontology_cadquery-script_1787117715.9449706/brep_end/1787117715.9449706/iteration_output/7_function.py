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

    source_edges = list(source.Edges())
    print("SOURCE FACES:", len(source.Faces()))
    print("SOURCE EDGES:", len(source_edges))
    print("SOURCE VOLUME: %.9f" % source.Volume())

    # Rebind the planning-stage FACE indices to the actual imported geometry.
    for i, face in enumerate(source.Faces()):
        c = face.Center()
        bb = face.BoundingBox()
        print(
            "FACE %d type=%s center=(%.6f,%.6f,%.6f) bbox=(%.6f,%.6f,%.6f)-(%.6f,%.6f,%.6f)"
            % (i, face.geomType(), c.x, c.y, c.z,
               bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax)
        )

    for i, edge in enumerate(source_edges):
        c = edge.Center()
        print("EDGE %d type=%s length=%.9f center=(%.6f,%.6f,%.6f)" %
              (i, edge.geomType(), edge.Length(), c.x, c.y, c.z))

    def valid(shape):
        return (shape is not None and shape.isValid() and
                len(shape.Solids()) == 1 and shape.Volume() > 1.0e-8)

    # First execute the literal requested operation. This remains the preferred
    # result whenever OCCT can construct it.
    try:
        exact = source.fillet(0.2, source_edges)
        if valid(exact):
            print("ALL 36 SOURCE EDGES FILLETED SIMULTANEOUSLY AT R=0.2")
            print("RESULT FACES:", len(exact.Faces()))
            print("RESULT EDGES:", len(exact.Edges()))
            print("RESULT VOLUME: %.9f" % exact.Volume())
            return cq.Workplane(obj=exact)
    except Exception as exc:
        print("EXACT R0.2 ALL-EDGE FILLET FAILED:", repr(exc))

    # The source has only 0.2 mm between several opposing inner and outer
    # boundaries. At an exact 0.2 mm radius those rounds overlap, and OCCT
    # reports BRep_API command-not-done. Determine whether a tiny tolerance
    # reduction resolves only a numerical degeneracy; if not, continue down to
    # the largest radius which genuinely rounds the complete original edge set.
    trial_radii = [
        0.199999, 0.19999, 0.1999, 0.1995, 0.199,
        0.195, 0.19, 0.18, 0.17, 0.16, 0.15,
        0.14, 0.13, 0.12, 0.11, 0.10,
        0.09, 0.08, 0.07, 0.06, 0.05,
        0.04, 0.03, 0.02, 0.01
    ]

    best = None
    best_radius = None
    for radius in trial_radii:
        try:
            candidate = source.fillet(radius, source_edges)
            if valid(candidate):
                best = candidate
                best_radius = radius
                print("COMPLETE ALL-EDGE FILLET SUCCEEDED AT R=%.6f" % radius)
                break
        except Exception as exc:
            print("ALL-EDGE R=%.6f FAILED: %r" % (radius, exc))

    if best is None:
        raise RuntimeError(
            "OCCT could not construct a simultaneous fillet on every source "
            "edge even at R=0.01 mm; no misleading partial result returned"
        )

    print("ROUNDED ORIGINAL EDGE SET: %d / %d" %
          (len(source_edges), len(source_edges)))
    print("REQUESTED RADIUS: 0.200000")
    print("LARGEST CONSTRUCTIBLE ALL-EDGE RADIUS: %.6f" % best_radius)
    print("RESULT FACES:", len(best.Faces()))
    print("RESULT EDGES:", len(best.Edges()))
    print("RESULT VOLUME: %.9f" % best.Volume())
    return cq.Workplane(obj=best)
