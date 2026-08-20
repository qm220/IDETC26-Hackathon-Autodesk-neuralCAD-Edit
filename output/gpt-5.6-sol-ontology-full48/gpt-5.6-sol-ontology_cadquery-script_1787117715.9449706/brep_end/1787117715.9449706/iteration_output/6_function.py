def my_cad_function(args):
    import os
    import math
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    solids = imported.solids().vals()
    if len(solids) != 1:
        raise ValueError("Expected one input solid, found %d" % len(solids))

    source = solids[0]
    if not source.isValid():
        raise ValueError("Imported STEP solid is invalid")

    radius = 0.2
    original_edges = list(source.Edges())

    print("SOURCE FACES:", len(source.Faces()))
    print("SOURCE EDGES:", len(original_edges))
    print("SOURCE VOLUME: %.9f" % source.Volume())

    # Bind the planning-stage face and edge indices to the imported geometry.
    for i, face in enumerate(source.Faces()):
        c = face.Center()
        bb = face.BoundingBox()
        print(
            "FACE %d type=%s center=(%.6f,%.6f,%.6f) bbox=(%.6f,%.6f,%.6f)-(%.6f,%.6f,%.6f)"
            % (i, face.geomType(), c.x, c.y, c.z,
               bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax)
        )

    for i, edge in enumerate(original_edges):
        c = edge.Center()
        print("EDGE %d type=%s length=%.9f center=(%.6f,%.6f,%.6f)" %
              (i, edge.geomType(), edge.Length(), c.x, c.y, c.z))

    def valid(shape):
        return (shape is not None and shape.isValid() and
                len(shape.Solids()) == 1 and shape.Volume() > 1.0e-8)

    # First try the literal simultaneous operation.
    try:
        result = source.fillet(radius, original_edges)
        if valid(result):
            print("SIMULTANEOUS EXACT R0.2 FILLET SUCCEEDED")
            print("RESULT FACES:", len(result.Faces()))
            print("RESULT EDGES:", len(result.Edges()))
            return cq.Workplane(obj=result)
    except Exception as exc:
        print("SIMULTANEOUS FILLET FAILED:", repr(exc))

    def point_tuple(v):
        return (v.X, v.Y, v.Z)

    def edge_descriptor(edge):
        c = edge.Center()
        bb = edge.BoundingBox()
        verts = edge.Vertices()
        pts = sorted([point_tuple(v) for v in verts])
        return {
            "type": edge.geomType(),
            "length": edge.Length(),
            "center": (c.x, c.y, c.z),
            "bbox": (bb.xmin, bb.ymin, bb.zmin,
                     bb.xmax, bb.ymax, bb.zmax),
            "points": pts
        }

    descriptors = [edge_descriptor(e) for e in original_edges]

    def dist3(a, b):
        return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2)

    def match_score(target, edge):
        d = edge_descriptor(edge)
        if d["type"] != target["type"]:
            return 1.0e9

        center_error = dist3(target["center"], d["center"])
        length_error = abs(target["length"] - d["length"])
        bbox_error = sum(abs(a-b) for a, b in zip(target["bbox"], d["bbox"]))

        # Adjacent rounds trim the ends of an unprocessed edge, while its
        # midpoint and supporting curve normally remain near the source edge.
        return 8.0 * center_error + length_error + 0.25 * bbox_error

    def run_sequence(order, label):
        shape = source
        successes = []
        failures = []

        for source_index in order:
            target = descriptors[source_index]
            candidates = []
            for current_edge in shape.Edges():
                score = match_score(target, current_edge)
                if score < 1.0e8:
                    candidates.append((score, current_edge))
            candidates.sort(key=lambda item: item[0])

            # Reject a candidate which is no longer geometrically associated
            # with the source edge. Such an edge may be a newly created fillet
            # boundary rather than the remaining source edge.
            candidates = [item for item in candidates if item[0] < 3.5]
            if not candidates:
                failures.append(source_index)
                continue

            applied = False
            # Occasionally the nearest candidate is a new boundary curve;
            # test several close matches and retain only a valid solid.
            for score, candidate_edge in candidates[:4]:
                try:
                    trial = shape.fillet(radius, [candidate_edge])
                    if valid(trial):
                        shape = trial
                        successes.append(source_index)
                        applied = True
                        print("%s: rounded source EDGE %d score=%.6f" %
                              (label, source_index, score))
                        break
                except Exception:
                    pass

            if not applied:
                failures.append(source_index)
                print("%s: EDGE %d could not be rounded in this order" %
                      (label, source_index))

        return shape, successes, failures

    indices = list(range(len(original_edges)))

    # Test several exact-radius orders. Filleting sequentially avoids the OCC
    # simultaneous-builder failure at the thin shell's high-valence vertices.
    orders = []
    orders.append(("circular_first", sorted(
        indices,
        key=lambda i: (0 if descriptors[i]["type"] == "CIRCLE" else 1,
                       descriptors[i]["length"])
    )))
    orders.append(("short_first", sorted(
        indices,
        key=lambda i: descriptors[i]["length"]
    )))
    orders.append(("long_first", sorted(
        indices,
        key=lambda i: -descriptors[i]["length"]
    )))
    orders.append(("lines_first", sorted(
        indices,
        key=lambda i: (0 if descriptors[i]["type"] == "LINE" else 1,
                       -descriptors[i]["length"])
    )))

    best_shape = None
    best_successes = []
    best_failures = indices

    for label, order in orders:
        try:
            candidate, successes, failures = run_sequence(order, label)
            print("%s: rounded %d/%d source edges" %
                  (label, len(successes), len(indices)))
            if valid(candidate) and len(successes) > len(best_successes):
                best_shape = candidate
                best_successes = successes
                best_failures = failures
            if valid(candidate) and not failures:
                print("ALL SOURCE EDGES ROUNDED AT EXACT R0.2")
                print("RESULT FACES:", len(candidate.Faces()))
                print("RESULT EDGES:", len(candidate.Edges()))
                print("RESULT VOLUME: %.9f" % candidate.Volume())
                return cq.Workplane(obj=candidate)
        except Exception as exc:
            print("SEQUENCE %s FAILED: %r" % (label, exc))

    if best_shape is None or not valid(best_shape):
        raise RuntimeError("No valid exact-radius rounded result was produced")

    print("RETURNING BEST VALID EXACT-R0.2 SEQUENTIAL RESULT")
    print("ROUNDED SOURCE EDGES:", len(best_successes), "/", len(indices))
    print("UNRESOLVED SOURCE EDGE INDICES:", best_failures)
    print("RESULT FACES:", len(best_shape.Faces()))
    print("RESULT EDGES:", len(best_shape.Edges()))
    print("RESULT VOLUME: %.9f" % best_shape.Volume())
    return cq.Workplane(obj=best_shape)
