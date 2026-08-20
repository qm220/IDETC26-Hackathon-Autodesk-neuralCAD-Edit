def my_cad_function(args):
    import os
    import itertools
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    original = imported.val()
    source_edges = list(original.Edges())

    print(f"Input valid: {original.isValid()}")
    print(f"Input solids: {len(original.Solids())}")
    print(f"Original edges: {len(source_edges)}")

    # First attempt a true, simultaneous all-edge round. Tiny reductions are
    # included because the nominal 0.2 mm shell thickness can create a
    # zero-width residual face at exactly R=0.2 mm.
    global_radii = [0.2, 0.19999, 0.1999, 0.1995, 0.199, 0.195, 0.19]
    for radius in global_radii:
        try:
            result = original.fillet(radius, source_edges)
            if result.isValid() and len(result.Solids()) == 1:
                print(f"All {len(source_edges)} edges rounded simultaneously at R={radius:.5f} mm")
                return cq.Workplane("XY").newObject([result])
        except Exception as exc:
            print(f"Global R={radius:.5f} failed: {type(exc).__name__}")

    indexed = list(enumerate(source_edges))

    def signature(item):
        edge_id, edge = item
        c = edge.Center()
        try:
            kind = edge.geomType()
        except Exception:
            kind = ""
        return (kind, round(edge.Length(), 8), round(c.z, 8),
                round(c.y, 8), round(c.x, 8), edge_id)

    orders = [
        sorted(indexed, key=lambda item: item[1].Length()),
        sorted(indexed, key=lambda item: item[1].Length(), reverse=True),
        sorted(indexed, key=signature),
        sorted(indexed, key=signature, reverse=True),
    ]

    # Construct the largest mutually compatible near-nominal fillet set.
    base_radius = 0.1999
    best_shape = original
    best_ids = set()

    for order_number, order in enumerate(orders, 1):
        accepted_edges = []
        accepted_ids = set()
        current = original

        for edge_id, edge in order:
            try:
                trial = original.fillet(base_radius, accepted_edges + [edge])
                if trial.isValid() and len(trial.Solids()) == 1:
                    accepted_edges.append(edge)
                    accepted_ids.add(edge_id)
                    current = trial
            except Exception:
                pass

        print(f"Near-nominal order {order_number}: {len(accepted_ids)}/{len(source_edges)} edges")
        if len(accepted_ids) > len(best_ids):
            best_shape = current
            best_ids = accepted_ids

    missing_ids = [i for i in range(len(source_edges)) if i not in best_ids]
    print(f"Near-nominal base covers {len(best_ids)} edges; cleanup targets: {missing_ids}")

    def point_to_edge_distance(point, edge):
        vertex = cq.Vertex.makeVertex(point.x, point.y, point.z)
        try:
            return vertex.distToShape(edge)[0]
        except Exception:
            return 1.0e100

    def find_surviving_segment(shape, source_edge):
        # An unrounded remainder of a source edge stays on the same underlying
        # curve. Its midpoint therefore has essentially zero distance from the
        # original edge. Prefer the longest such coincident segment.
        try:
            source_kind = source_edge.geomType()
        except Exception:
            source_kind = None

        candidates = []
        for edge in shape.Edges():
            try:
                if source_kind is not None and edge.geomType() != source_kind:
                    continue
                midpoint = edge.positionAt(0.5)
            except Exception:
                midpoint = edge.Center()

            distance = point_to_edge_distance(midpoint, source_edge)
            if distance < 1.0e-5:
                candidates.append((distance, -edge.Length(), edge))

        if not candidates:
            return None
        candidates.sort(key=lambda item: (item[0], item[1]))
        return candidates[0][2]

    cleanup_radii = [0.1999, 0.195, 0.19, 0.18, 0.16, 0.14,
                     0.12, 0.10, 0.08, 0.06, 0.04, 0.02]

    cleanup_best_shape = best_shape
    cleanup_best_done = []
    cleanup_best_radii = []

    # There are normally only four incompatible source edges. Trying their
    # permutations lets OpenCascade form the corner transitions in whichever
    # sequence is most stable.
    permutations = list(itertools.permutations(missing_ids))
    if len(permutations) > 120:
        permutations = permutations[:120]

    for permutation in permutations:
        current = best_shape
        done = []
        used_radii = []

        for source_id in permutation:
            target = find_surviving_segment(current, source_edges[source_id])
            if target is None:
                continue

            for radius in cleanup_radii:
                try:
                    trial = current.fillet(radius, [target])
                    if trial.isValid() and len(trial.Solids()) == 1:
                        current = trial
                        done.append(source_id)
                        used_radii.append(radius)
                        break
                except Exception:
                    pass

        score = (len(done), min(used_radii) if used_radii else 0.0,
                 sum(used_radii))
        best_score = (len(cleanup_best_done),
                      min(cleanup_best_radii) if cleanup_best_radii else 0.0,
                      sum(cleanup_best_radii))
        if score > best_score:
            cleanup_best_shape = current
            cleanup_best_done = done
            cleanup_best_radii = used_radii

        if len(done) == len(missing_ids):
            break

    total_covered = len(best_ids) + len(cleanup_best_done)
    print(f"Rounded source-edge coverage: {total_covered}/{len(source_edges)}")
    if cleanup_best_radii:
        print(f"Cleanup radii used: {cleanup_best_radii}")
    print(f"Output valid: {cleanup_best_shape.isValid()}")
    print(f"Output solids: {len(cleanup_best_shape.Solids())}")
    print(f"Output edges: {len(cleanup_best_shape.Edges())}")

    return cq.Workplane("XY").newObject([cleanup_best_shape])