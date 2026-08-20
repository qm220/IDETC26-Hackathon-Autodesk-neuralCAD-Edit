def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    solids = imported.solids().vals()
    if len(solids) != 1:
        raise ValueError("Expected exactly one input solid, found %d" % len(solids))

    solid = solids[0]
    if not solid.isValid():
        raise ValueError("Imported STEP solid is invalid")

    faces = solid.Faces()
    edges = [e for e in solid.Edges() if e.Length() > 1.0e-7]
    print("INPUT VALID:", solid.isValid())
    print("INPUT FACES:", len(faces))
    print("INPUT EDGES:", len(edges))
    print("INPUT VOLUME: %.9f" % solid.Volume())

    # Rebind the planned face indices and inspect the actual STEP geometry.
    for i, face in enumerate(faces):
        bb = face.BoundingBox()
        c = face.Center()
        print(
            "FACE %d type=%s center=(%.6f, %.6f, %.6f) bbox=(%.6f, %.6f, %.6f)-(%.6f, %.6f, %.6f)"
            % (i, face.geomType(), c.x, c.y, c.z,
               bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax)
        )

    # Print and retain stable indices for every original edge.
    edge_data = []
    for i, edge in enumerate(edges):
        c = edge.Center()
        length = edge.Length()
        edge_data.append((i, length, c.x, c.y, c.z))
        print(
            "EDGE %d type=%s length=%.9f center=(%.6f, %.6f, %.6f)"
            % (i, edge.geomType(), length, c.x, c.y, c.z)
        )

    radius = 0.2

    def make_fillet(indices):
        if not indices:
            return solid
        candidate = solid.fillet(radius, [edges[i] for i in indices])
        if candidate is None:
            raise RuntimeError("fillet returned no shape")
        if not candidate.isValid():
            raise RuntimeError("fillet produced an invalid shape")
        if len(candidate.Solids()) != 1:
            raise RuntimeError("fillet did not preserve one solid")
        return candidate

    # Confirm whether the requested single all-edge operation is feasible.
    try:
        result = make_fillet(list(range(len(edges))))
        print("EXACT GLOBAL ALL-EDGE FILLET SUCCEEDED AT R=0.200000 MM")
        print("RESULT FACES:", len(result.Faces()))
        print("RESULT EDGES:", len(result.Edges()))
        print("RESULT VOLUME: %.9f" % result.Volume())
        return cq.Workplane(obj=result)
    except Exception as exc:
        print("EXACT GLOBAL ALL-EDGE FILLET FAILED:", repr(exc))

    # The previous iteration incorrectly substituted R=0.08. Do not alter the
    # requested radius. Instead, determine which original edges OCC can round
    # at exactly R=0.2 and seek the largest compatible simultaneous subset.
    individually_viable = []
    for i in range(len(edges)):
        try:
            make_fillet([i])
            individually_viable.append(i)
            print("INDIVIDUAL R=0.2 EDGE %d: SUCCESS" % i)
        except Exception as exc:
            print("INDIVIDUAL R=0.2 EDGE %d: FAILED %r" % (i, exc))

    if not individually_viable:
        raise RuntimeError("No original edge can be filleted at the specified R=0.2 mm")

    data = {i: (length, x, y, z) for i, length, x, y, z in edge_data}
    orders = [
        list(individually_viable),
        list(reversed(individually_viable)),
        sorted(individually_viable, key=lambda i: data[i][0]),
        sorted(individually_viable, key=lambda i: -data[i][0]),
        sorted(individually_viable, key=lambda i: (data[i][1], data[i][2], data[i][3], i)),
        sorted(individually_viable, key=lambda i: (-data[i][1], -data[i][2], -data[i][3], i)),
        sorted(individually_viable, key=lambda i: (abs(data[i][3]), abs(data[i][1]), abs(data[i][2]), i)),
        sorted(individually_viable, key=lambda i: (-abs(data[i][3]), -abs(data[i][1]), -abs(data[i][2]), i)),
    ]

    best_indices = []
    best_shape = None
    best_length = -1.0

    for order_number, order in enumerate(orders):
        chosen = []
        chosen_shape = None
        for edge_index in order:
            trial = sorted(chosen + [edge_index])
            try:
                candidate = make_fillet(trial)
                chosen = trial
                chosen_shape = candidate
            except Exception:
                pass

        # Revisit rejected edges because later compatibility can depend on order.
        changed = True
        while changed:
            changed = False
            for edge_index in individually_viable:
                if edge_index in chosen:
                    continue
                trial = sorted(chosen + [edge_index])
                try:
                    candidate = make_fillet(trial)
                    chosen = trial
                    chosen_shape = candidate
                    changed = True
                except Exception:
                    pass

        total_length = sum(data[i][0] for i in chosen)
        print("GREEDY ORDER %d: %d/%d edges, total original edge length %.9f"
              % (order_number, len(chosen), len(edges), total_length))
        if (len(chosen), total_length) > (len(best_indices), best_length):
            best_indices = chosen
            best_shape = chosen_shape
            best_length = total_length

    if best_shape is None:
        raise RuntimeError("Could not construct any valid exact-radius fillet result")

    omitted = [i for i in range(len(edges)) if i not in best_indices]
    print("EXACT R=0.2 SELECTED ORIGINAL EDGES:", best_indices)
    print("EXACT R=0.2 OMITTED ORIGINAL EDGES:", omitted)
    print("RESULT VALID:", best_shape.isValid())
    print("RESULT SOLIDS:", len(best_shape.Solids()))
    print("RESULT FACES:", len(best_shape.Faces()))
    print("RESULT EDGES:", len(best_shape.Edges()))
    print("RESULT VOLUME: %.9f" % best_shape.Volume())
    print("WARNING: Source topology does not admit a simultaneous exact R=0.2 fillet on all 36 original edges; returning the largest exact-radius compatible subset found.")

    return cq.Workplane(obj=best_shape)