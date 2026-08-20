def my_cad_function(args):
    import os
    import random
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

    # Rebind the planning FACE indices to the actual imported STEP geometry.
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

    requested_radius = 0.2

    # First perform the literal requested operation on the complete original
    # edge collection.
    try:
        result = source.fillet(requested_radius, edges)
        if acceptable(result):
            print("EXACT R=0.2 ALL-EDGE FILLET SUCCEEDED")
            print("FILLETED ORIGINAL EDGES: %d / %d" % (len(edges), len(edges)))
            print("FILLET RADIUS: 0.200000 mm")
            print("RESULT FACES:", len(result.Faces()))
            print("RESULT EDGES:", len(result.Edges()))
            print("RESULT VOLUME: %.9f" % result.Volume())
            return cq.Workplane(obj=result)
    except Exception as exc:
        print("EXACT R=0.2 ALL-EDGE FILLET FAILED:", repr(exc))

    # The source contains several 0.2 mm walls, so simultaneous R=0.2 rounds
    # on both boundaries can geometrically overlap. Unlike the previous
    # iteration, do not silently change the requested radius. Search several
    # deterministic edge orders for the largest valid subset that OCC can
    # round at the exact requested R=0.2 mm.
    indexed = list(enumerate(edges))
    orders = []
    orders.append(indexed[:])
    orders.append(list(reversed(indexed)))
    orders.append(sorted(indexed, key=lambda p: p[1].Length()))
    orders.append(sorted(indexed, key=lambda p: p[1].Length(), reverse=True))
    orders.append(sorted(indexed, key=lambda p: (p[1].geomType(), p[1].Length())))
    orders.append(sorted(indexed, key=lambda p: (p[1].geomType(), -p[1].Length())))

    rng = random.Random(192)
    for _ in range(6):
        order = indexed[:]
        rng.shuffle(order)
        orders.append(order)

    best_indices = []
    best_shape = None

    for order_number, order in enumerate(orders):
        selected_indices = []
        selected_edges = []
        current = None

        for edge_index, edge in order:
            trial_edges = selected_edges + [edge]
            try:
                candidate = source.fillet(requested_radius, trial_edges)
                if acceptable(candidate):
                    selected_indices.append(edge_index)
                    selected_edges.append(edge)
                    current = candidate
            except Exception:
                pass

        print(
            "R=0.2 SEARCH ORDER %d: %d / %d original edges"
            % (order_number, len(selected_indices), len(edges))
        )
        if len(selected_indices) > len(best_indices):
            best_indices = selected_indices[:]
            best_shape = current

    if best_shape is None:
        raise RuntimeError("No original edge could be filleted at R=0.2 mm")

    # Try to augment the best subset once more in original index order.
    best_set = set(best_indices)
    changed = True
    while changed:
        changed = False
        for i, edge in indexed:
            if i in best_set:
                continue
            trial_indices = sorted(list(best_set | {i}))
            trial_edges = [edges[j] for j in trial_indices]
            try:
                candidate = source.fillet(requested_radius, trial_edges)
                if acceptable(candidate):
                    best_set.add(i)
                    best_shape = candidate
                    changed = True
            except Exception:
                pass

    best_indices = sorted(best_set)
    omitted = [i for i in range(len(edges)) if i not in best_set]
    print("EXACT FILLET RADIUS: 0.200000 mm")
    print("FILLETED ORIGINAL EDGES: %d / %d" % (len(best_indices), len(edges)))
    print("FILLETED EDGE INDICES:", best_indices)
    print("UNFILLETED EDGE INDICES:", omitted)
    print("RESULT FACES:", len(best_shape.Faces()))
    print("RESULT EDGES:", len(best_shape.Edges()))
    print("RESULT VOLUME: %.9f" % best_shape.Volume())
    return cq.Workplane(obj=best_shape)
