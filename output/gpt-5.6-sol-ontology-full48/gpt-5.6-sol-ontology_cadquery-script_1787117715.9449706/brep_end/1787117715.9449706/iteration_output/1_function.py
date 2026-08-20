def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    solids = imported.solids().vals()
    if len(solids) != 1:
        raise ValueError("Expected exactly one input solid, found %d" % len(solids))

    solid = solids[0]
    if not solid.isValid():
        raise ValueError("Imported STEP solid is invalid")

    print("INPUT VALID:", solid.isValid())
    print("INPUT FACES:", len(solid.Faces()))
    print("INPUT EDGES:", len(solid.Edges()))
    print("INPUT VOLUME: %.9f" % solid.Volume())

    # Rebind the planned FACE indices to the imported STEP geometry.
    for i, face in enumerate(solid.Faces()):
        bb = face.BoundingBox()
        c = face.Center()
        print(
            "FACE %d type=%s center=(%.6f, %.6f, %.6f) bbox=(%.6f, %.6f, %.6f)-(%.6f, %.6f, %.6f)"
            % (i, face.geomType(), c.x, c.y, c.z,
               bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax)
        )

    # Capture every non-degenerate edge from the original, unmodified B-rep.
    all_edges = [e for e in solid.Edges() if e.Length() > 1.0e-7]
    if len(all_edges) != len(solid.Edges()):
        raise RuntimeError("Unexpected degenerate edges in the source model")
    print("ALL ORIGINAL EDGES SELECTED:", len(all_edges))

    # OCC can reject a mathematically limiting fillet when the requested radius
    # exactly equals the 0.2 mm wall thickness. First request the exact value,
    # then test only kernel-scale inward perturbations that remain 0.2 mm at
    # ordinary CAD precision. Larger reductions are diagnostic only.
    trial_radii = [
        0.2,
        0.199999999,
        0.19999999,
        0.1999999,
        0.199999,
        0.19999,
        0.1999,
        0.199,
        0.195,
        0.19,
        0.18,
        0.16,
        0.14,
        0.12,
        0.10,
        0.08,
        0.05,
    ]

    accepted = None
    accepted_radius = None
    for radius in trial_radii:
        try:
            candidate = solid.fillet(radius, all_edges)
            if candidate is None:
                raise RuntimeError("fillet returned no shape")
            if not candidate.isValid():
                raise RuntimeError("fillet produced an invalid shape")
            if len(candidate.Solids()) != 1:
                raise RuntimeError("fillet did not preserve one solid")
            if len(candidate.Faces()) <= len(solid.Faces()):
                raise RuntimeError("no fillet faces were generated")

            print("GLOBAL ALL-EDGE FILLET SUCCEEDED AT R=%.9f MM" % radius)
            print("RESULT VALID:", candidate.isValid())
            print("RESULT SOLIDS:", len(candidate.Solids()))
            print("RESULT FACES:", len(candidate.Faces()))
            print("RESULT EDGES:", len(candidate.Edges()))
            print("RESULT VOLUME: %.9f" % candidate.Volume())
            accepted = candidate
            accepted_radius = radius
            break
        except Exception as exc:
            print("GLOBAL ALL-EDGE FILLET FAILED AT R=%.9f MM: %r" % (radius, exc))

    if accepted is None:
        raise RuntimeError("OCC could not construct a global fillet on all original edges, even at diagnostic radii")

    if accepted_radius < 0.199999:
        print("WARNING: Exact/near-exact R=0.2 mm remains topologically infeasible; returned diagnostic all-edge result at R=%.9f mm" % accepted_radius)
    elif accepted_radius != 0.2:
        print("NOTE: Used a kernel-scale perturbation of the nominal R=0.2 mm value")

    return cq.Workplane(obj=accepted)
