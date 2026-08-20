def my_cad_function(args):
    import os
    import random
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    original = imported.val()
    original_edges = list(original.Edges())
    radius = 0.2

    print(f"Input valid: {original.isValid()}")
    print(f"Input solids: {len(original.Solids())}")
    print(f"Input edges: {len(original_edges)}")

    # First try the literal operation requested by the user.
    try:
        direct = original.fillet(radius, original_edges)
        if direct.isValid() and len(direct.Solids()) == 1:
            print("All original edges accepted in one fillet operation.")
            print(f"Output edges: {len(direct.Edges())}")
            return cq.Workplane("XY").newObject([direct])
    except Exception as exc:
        print(f"Single all-edge fillet was rejected: {type(exc).__name__}")

    indexed = list(enumerate(original_edges))

    def edge_key(item):
        i, edge = item
        c = edge.Center()
        try:
            kind = edge.geomType()
        except Exception:
            kind = ""
        return (kind, round(edge.Length(), 8), round(c.z, 8), round(c.y, 8), round(c.x, 8), i)

    # OCC fillets at intersecting thin-wall corners are order dependent. Search
    # several deterministic maximal compatible sets instead of accepting the
    # first length-sorted set.
    orders = []
    orders.append(sorted(indexed, key=lambda x: x[1].Length(), reverse=True))
    orders.append(sorted(indexed, key=lambda x: x[1].Length()))
    orders.append(sorted(indexed, key=edge_key))
    orders.append(sorted(indexed, key=edge_key, reverse=True))

    rng = random.Random(33203)
    for _ in range(10):
        order = indexed[:]
        rng.shuffle(order)
        orders.append(order)

    best_shape = original
    best_ids = set()
    best_length = 0.0

    for order_number, order in enumerate(orders):
        selected_edges = []
        selected_ids = set()
        candidate_shape = original

        for edge_id, edge in order:
            try:
                trial = original.fillet(radius, selected_edges + [edge])
                if trial.isValid() and len(trial.Solids()) == 1:
                    selected_edges.append(edge)
                    selected_ids.add(edge_id)
                    candidate_shape = trial
            except Exception:
                pass

        selected_length = sum(original_edges[i].Length() for i in selected_ids)
        score = (len(selected_ids), selected_length)
        best_score = (len(best_ids), best_length)
        print(
            f"Search order {order_number + 1}: "
            f"{len(selected_ids)}/{len(original_edges)} original edges, "
            f"length {selected_length:.4f}"
        )

        if score > best_score:
            best_shape = candidate_shape
            best_ids = selected_ids
            best_length = selected_length

        if len(best_ids) == len(original_edges):
            break

    print(
        f"Best simultaneous set: {len(best_ids)}/{len(original_edges)} "
        f"original edges"
    )

    # Attempt omitted source edges on the evolving result. Multiple points are
    # used because adjacent rounds can shorten an edge enough that its original
    # midpoint is no longer the most reliable locator.
    result_shape = best_shape
    added_ids = set()
    omitted = [(i, e) for i, e in indexed if i not in best_ids]
    omitted.sort(key=lambda item: item[1].Length(), reverse=True)

    def sample_edge(edge):
        points = []
        for t in (0.15, 0.3, 0.5, 0.7, 0.85):
            try:
                points.append(edge.positionAt(t))
            except Exception:
                pass
        if not points:
            points.append(edge.Center())
        return points

    # Repeat because one successful operation can expose a better mapping for
    # another omitted edge.
    for pass_number in range(3):
        pass_added = 0

        for edge_id, source_edge in omitted:
            if edge_id in added_ids:
                continue

            source_points = sample_edge(source_edge)
            ranked = []

            for current_edge in result_shape.Edges():
                distances = []
                for p in source_points:
                    try:
                        marker = cq.Vertex.makeVertex(p.x, p.y, p.z)
                        distances.append(marker.distToShape(current_edge)[0])
                    except Exception:
                        pass

                if not distances:
                    continue

                distances.sort()
                # Favor edges that remain close to several points of the
                # original edge, not merely a crossing blend boundary.
                score = distances[0] + 0.35 * distances[min(1, len(distances) - 1)]
                ranked.append((score, distances[0], current_edge))

            ranked.sort(key=lambda item: item[0])

            for score, minimum_distance, candidate in ranked[:10]:
                if minimum_distance > radius + 0.03:
                    continue
                try:
                    trial = result_shape.fillet(radius, [candidate])
                    if trial.isValid() and len(trial.Solids()) == 1:
                        result_shape = trial
                        added_ids.add(edge_id)
                        pass_added += 1
                        break
                except Exception:
                    pass

        print(f"Sequential pass {pass_number + 1}: added {pass_added} edges")
        if pass_added == 0:
            break

    accepted = len(best_ids | added_ids)
    print(f"Requested source-edge operations accepted: {accepted}/{len(original_edges)}")
    print(f"Output valid: {result_shape.isValid()}")
    print(f"Output solids: {len(result_shape.Solids())}")
    print(f"Output edges: {len(result_shape.Edges())}")

    return cq.Workplane("XY").newObject([result_shape])