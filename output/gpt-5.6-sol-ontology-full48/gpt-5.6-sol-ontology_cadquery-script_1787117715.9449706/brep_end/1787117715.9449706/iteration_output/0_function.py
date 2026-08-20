def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)

    solids = imported.solids().vals()
    if len(solids) != 1:
        raise ValueError("Expected exactly one input solid, found %d" % len(solids))
    solid = solids[0]

    print("INPUT VALID:", solid.isValid())
    print("INPUT SOLIDS:", len(solids))
    print("INPUT FACES:", len(solid.Faces()))
    print("INPUT EDGES:", len(solid.Edges()))
    print("INPUT VOLUME: %.9f" % solid.Volume())

    for i, face in enumerate(solid.Faces()):
        bb = face.BoundingBox()
        c = face.Center()
        try:
            geom_type = face.geomType()
        except Exception:
            geom_type = "UNKNOWN"
        print(
            "FACE %d type=%s center=(%.6f, %.6f, %.6f) "
            "bbox=(%.6f, %.6f, %.6f)-(%.6f, %.6f, %.6f) area=%.9f"
            % (i, geom_type, c.x, c.y, c.z,
               bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax,
               face.Area())
        )

    original_edges = []
    for i, edge in enumerate(solid.Edges()):
        length = edge.Length()
        c = edge.Center()
        bb = edge.BoundingBox()
        try:
            geom_type = edge.geomType()
        except Exception:
            geom_type = "UNKNOWN"
        print(
            "EDGE %d type=%s length=%.9f center=(%.6f, %.6f, %.6f) "
            "bbox=(%.6f, %.6f, %.6f)-(%.6f, %.6f, %.6f)"
            % (i, geom_type, length, c.x, c.y, c.z,
               bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax)
        )
        if length > 1.0e-7:
            original_edges.append(edge)

    print("NON-DEGENERATE ORIGINAL EDGES SELECTED:", len(original_edges))
    if len(original_edges) != len(solid.Edges()):
        print("DEGENERATE EDGES OMITTED:", len(solid.Edges()) - len(original_edges))

    radius = 0.2
    try:
        # Apply one global constant-radius rolling-ball fillet to the complete
        # collection captured from the original, unmodified B-rep.
        filleted_solid = solid.fillet(radius, original_edges)
        if filleted_solid is None:
            raise RuntimeError("The OCC fillet operation returned no shape")

        result_solids = filleted_solid.Solids()
        print("FILLET SUCCEEDED")
        print("RESULT VALID:", filleted_solid.isValid())
        print("RESULT SOLIDS:", len(result_solids))
        print("RESULT FACES:", len(filleted_solid.Faces()))
        print("RESULT EDGES:", len(filleted_solid.Edges()))
        print("RESULT VOLUME: %.9f" % filleted_solid.Volume())

        if not filleted_solid.isValid():
            raise RuntimeError("Global all-edge fillet produced an invalid shape")
        if len(result_solids) != 1:
            raise RuntimeError("Global all-edge fillet did not preserve one closed solid")

        return cq.Workplane(obj=filleted_solid)
    except Exception as exc:
        print("GLOBAL ALL-EDGE R=0.2 MM FILLET FAILED:", repr(exc))
        print("The requested radius equals the nominal 0.2 mm side-wall thickness; no radius reduction or edge exclusion was applied.")
        # Return the valid source body so its geometry and printed edge data can
        # be inspected during this diagnostic first iteration.
        return cq.Workplane(obj=solid)