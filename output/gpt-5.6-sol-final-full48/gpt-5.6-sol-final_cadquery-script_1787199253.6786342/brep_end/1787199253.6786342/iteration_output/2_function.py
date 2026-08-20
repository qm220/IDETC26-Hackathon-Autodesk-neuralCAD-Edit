def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    original = imported.val()
    original_edges = list(original.Edges())
    radius = 0.2

    print(f"Input valid: {original.isValid()}")
    print(f"Input solids: {len(original.Solids())}")
    print(f"Input edges: {len(original_edges)}")

    # A single all-edge OCC fillet can fail when several rounds meet across
    # thin walls. Build the largest compatible simultaneous set first.
    indexed_edges = list(enumerate(original_edges))
    indexed_edges.sort(key=lambda item: item[1].Length(), reverse=True)

    selected = []
    selected_ids = set()
    best_shape = original

    for edge_id, edge in indexed_edges:
        trial_edges = selected + [edge]
        try:
            trial = original.fillet(radius, trial_edges)
            if trial.isValid() and len(trial.Solids()) == 1:
                selected = trial_edges
                selected_ids.add(edge_id)
                best_shape = trial
        except Exception:
            pass

    print(f"Compatible original edges filleted together: {len(selected_ids)}")

    # Attempt omitted original edges individually on the evolving result.
    # Their original midpoint remains a reliable locator after neighboring
    # edges have been shortened by the first fillet operation.
    result_shape = best_shape
    individually_added = 0

    omitted = [(i, e) for i, e in enumerate(original_edges) if i not in selected_ids]
    omitted.sort(key=lambda item: item[1].Length(), reverse=True)

    for edge_id, source_edge in omitted:
        p = source_edge.Center()
        marker = cq.Vertex.makeVertex(p.x, p.y, p.z)
        candidates = []

        for current_edge in result_shape.Edges():
            try:
                distance = marker.distToShape(current_edge)[0]
                c = current_edge.Center()
                center_distance = ((c.x - p.x) ** 2 + (c.y - p.y) ** 2 + (c.z - p.z) ** 2) ** 0.5
                score = distance + 0.001 * center_distance
                candidates.append((score, distance, current_edge))
            except Exception:
                continue

        candidates.sort(key=lambda item: item[0])

        # Test a few close mappings because a newly created blend boundary can
        # occasionally be closer than the shortened remnant of the source edge.
        for score, distance, candidate in candidates[:4]:
            if distance > 0.21:
                continue
            try:
                trial = result_shape.fillet(radius, [candidate])
                if trial.isValid() and len(trial.Solids()) == 1:
                    result_shape = trial
                    individually_added += 1
                    break
            except Exception:
                pass

    print(f"Additional edges filleted individually: {individually_added}")
    print(f"Total requested-edge operations accepted: {len(selected_ids) + individually_added}/{len(original_edges)}")
    print(f"Output valid: {result_shape.isValid()}")
    print(f"Output solids: {len(result_shape.Solids())}")
    print(f"Output edges: {len(result_shape.Edges())}")

    return cq.Workplane("XY").newObject([result_shape])