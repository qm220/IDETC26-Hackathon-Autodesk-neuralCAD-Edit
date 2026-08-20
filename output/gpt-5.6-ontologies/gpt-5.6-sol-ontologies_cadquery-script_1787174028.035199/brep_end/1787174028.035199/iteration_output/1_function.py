def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root_shape = imported.val() if hasattr(imported, "val") else imported

    solids = root_shape.Solids()
    if len(solids) != 1:
        raise ValueError(f"Expected one solid, found {len(solids)}")

    original = solids[0]
    radius = 0.2
    original_edges = list(original.Edges())
    edge_count = len(original_edges)

    print(f"Input valid: {original.isValid()}")
    print(f"Original edges targeted: {edge_count}")

    def apply_fillet(shape, edges):
        if not edges:
            return shape
        try:
            candidate = shape.fillet(radius, edges)
            if candidate is not None and candidate.isValid() and len(candidate.Solids()) == 1:
                return candidate
        except Exception:
            pass
        return None

    def point_to_edge_distance(point, edge):
        try:
            vertex = cq.Vertex.makeVertex(point.x, point.y, point.z)
            return vertex.distance(edge)
        except Exception:
            try:
                return point.sub(edge.Center()).Length
            except Exception:
                return 1.0e99

    def matching_edge(shape, reference_edge):
        try:
            reference_type = reference_edge.geomType()
        except Exception:
            reference_type = None

        typed = []
        untyped = []
        for edge in shape.Edges():
            try:
                edge_type = edge.geomType()
            except Exception:
                edge_type = None
            (typed if edge_type == reference_type else untyped).append(edge)

        pool = typed if typed else untyped
        best_edge = None
        best_score = 1.0e99

        for edge in pool:
            distances = []
            for parameter in (0.15, 0.35, 0.5, 0.65, 0.85):
                try:
                    point = edge.positionAt(parameter)
                except Exception:
                    point = edge.Center()
                distances.append(point_to_edge_distance(point, reference_edge))

            carrier_error = max(distances)
            center_error = point_to_edge_distance(edge.Center(), reference_edge)
            score = carrier_error * 1000.0 + center_error - min(edge.Length(), reference_edge.Length()) * 1.0e-7
            if score < best_score:
                best_score = score
                best_edge = edge

        return best_edge, best_score

    # OCC can fail when all edges are supplied in one operation even though
    # compatible subsets and subsequent blends are valid. First seek the
    # largest simultaneous subset, which also creates correct corner patches.
    best_shape = None
    best_indices = []

    all_at_once = apply_fillet(original, original_edges)
    if all_at_once is not None:
        best_shape = all_at_once
        best_indices = list(range(edge_count))
        print("All original edges filleted in one operation")
    else:
        print("Single all-edge operation failed; searching compatible subsets")

    # A single troublesome edge is a common cause of an OCC all-edge failure.
    if best_shape is None:
        for omitted in range(edge_count):
            indices = [i for i in range(edge_count) if i != omitted]
            candidate = apply_fillet(original, [original_edges[i] for i in indices])
            if candidate is not None:
                best_shape = candidate
                best_indices = indices
                print(f"Valid {edge_count - 1}-edge simultaneous fillet found; initially omitted EDGE {omitted}")
                break

    # If no N-1 subset works, construct maximal compatible simultaneous sets
    # using several deterministic edge orders.
    if best_shape is None:
        lengths = [edge.Length() for edge in original_edges]
        types = []
        for edge in original_edges:
            try:
                types.append(edge.geomType())
            except Exception:
                types.append("")

        orders = [
            list(range(edge_count)),
            sorted(range(edge_count), key=lambda i: lengths[i]),
            sorted(range(edge_count), key=lambda i: lengths[i], reverse=True),
            sorted(range(edge_count), key=lambda i: (types[i] != "CIRCLE", lengths[i])),
        ]

        for order_number, order in enumerate(orders):
            accepted = []
            accepted_shape = original
            for index in order:
                trial_indices = accepted + [index]
                trial = apply_fillet(original, [original_edges[i] for i in trial_indices])
                if trial is not None:
                    accepted = trial_indices
                    accepted_shape = trial

            print(f"Subset order {order_number}: {len(accepted)}/{edge_count} edges accepted")
            if len(accepted) > len(best_indices):
                best_indices = accepted
                best_shape = accepted_shape

    if best_shape is None:
        raise ValueError("No valid 0.2 mm edge fillets could be constructed")

    result = best_shape
    completed = set(best_indices)
    pending = [i for i in range(edge_count) if i not in completed]

    # Add edges excluded from the simultaneous operation. Rematching uses the
    # unchanged carrier curve of each original edge, because adjacent rounds
    # may trim and renumber that edge.
    progress = True
    pass_number = 0
    while pending and progress and pass_number < 5:
        progress = False
        pass_number += 1

        # First try all remaining carrier edges together so OCC can make their
        # shared vertex patches simultaneously.
        mapped = []
        mapped_indices = []
        for index in pending:
            edge, score = matching_edge(result, original_edges[index])
            if edge is not None and score < 1.0:
                mapped.append(edge)
                mapped_indices.append(index)

        if mapped and len(mapped_indices) == len(pending):
            trial = apply_fillet(result, mapped)
            if trial is not None:
                result = trial
                completed.update(mapped_indices)
                pending = []
                print(f"Pass {pass_number}: filleted all remaining edges as one group")
                break

        # Otherwise add individually and retry skipped edges on later passes.
        next_pending = []
        for index in pending:
            edge, score = matching_edge(result, original_edges[index])
            if edge is None or score >= 1.0:
                next_pending.append(index)
                continue

            trial = apply_fillet(result, [edge])
            if trial is not None:
                result = trial
                completed.add(index)
                progress = True
                print(f"Pass {pass_number}: filleted original EDGE {index}")
            else:
                next_pending.append(index)

        pending = next_pending

    if pending:
        print(f"WARNING: unable to explicitly process original edges: {pending}")
    else:
        print(f"Successfully processed all {edge_count} original edges at R={radius} mm")

    if not result.isValid() or len(result.Solids()) != 1:
        raise ValueError("Final filleted result is not a valid single solid")

    print(f"Result valid: {result.isValid()}")
    print(f"Result solids: {len(result.Solids())}")
    print(f"Result faces: {len(result.Faces())}")
    print(f"Result edges: {len(result.Edges())}")
    print(f"Result volume: {result.Volume():.6f} mm^3")
    print(f"Original edge operations completed: {len(completed)}/{edge_count}")

    return cq.Workplane(obj=result)