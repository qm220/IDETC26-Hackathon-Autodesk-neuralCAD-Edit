def my_cad_function(args):
    import os
    import random
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported
    solids = list(root.Solids())
    if len(solids) != 1:
        raise ValueError(f"Expected one input solid, found {len(solids)}")

    original = solids[0]
    original_edges = list(original.Edges())
    radius = 0.2
    edge_count = len(original_edges)

    print(f"Input valid: {original.isValid()}")
    print(f"Original edge count: {edge_count}")

    def valid_single(shape):
        return shape is not None and shape.isValid() and len(shape.Solids()) == 1

    def fillet(shape, edges):
        if not edges:
            return shape
        try:
            candidate = shape.fillet(radius, edges)
            return candidate if valid_single(candidate) else None
        except Exception:
            return None

    def edge_type(edge):
        try:
            return edge.geomType()
        except Exception:
            return "UNKNOWN"

    def point_distance_to_edge(point, edge):
        try:
            vertex = cq.Vertex.makeVertex(point.x, point.y, point.z)
            return vertex.distance(edge)
        except Exception:
            return 1.0e100

    def carrier_error(candidate, reference):
        errors = []
        for t in (0.12, 0.28, 0.5, 0.72, 0.88):
            try:
                point = candidate.positionAt(t)
            except Exception:
                point = candidate.Center()
            errors.append(point_distance_to_edge(point, reference))
        return max(errors)

    def matching_edge(shape, reference, tolerance=0.03):
        rtype = edge_type(reference)
        best = None
        best_error = 1.0e100
        best_center = 1.0e100
        for edge in shape.Edges():
            if edge_type(edge) != rtype:
                continue
            error = carrier_error(edge, reference)
            center_error = point_distance_to_edge(edge.Center(), reference)
            if (error, center_error) < (best_error, best_center):
                best = edge
                best_error = error
                best_center = center_error
        if best is not None and best_error <= tolerance:
            return best, best_error
        return None, best_error

    # First attempt the literal operation requested by the user.
    direct = fillet(original, original_edges)
    if direct is not None:
        print(f"Successfully filleted all {edge_count} original edges simultaneously at R={radius} mm")
        return cq.Workplane(obj=direct)

    print("All-edge simultaneous fillet failed; searching compatible operation orders")
    lengths = [edge.Length() for edge in original_edges]
    types = [edge_type(edge) for edge in original_edges]

    orders = [
        list(range(edge_count)),
        list(reversed(range(edge_count))),
        sorted(range(edge_count), key=lambda i: lengths[i]),
        sorted(range(edge_count), key=lambda i: lengths[i], reverse=True),
        sorted(range(edge_count), key=lambda i: (types[i], lengths[i])),
        sorted(range(edge_count), key=lambda i: (types[i], -lengths[i])),
    ]

    # Deterministic randomized orders help avoid OCC's order-dependent corner
    # failures while keeping repeated executions reproducible.
    rng = random.Random(721903)
    for _ in range(18):
        order = list(range(edge_count))
        rng.shuffle(order)
        orders.append(order)

    best_shape = original
    best_indices = []

    # Build simultaneous subsets on the unchanged source solid. Simultaneous
    # construction is preferred because OCC then creates shared vertex blends
    # and setback patches consistently.
    for order_number, order in enumerate(orders):
        accepted = []
        accepted_shape = original
        for index in order:
            trial_indices = accepted + [index]
            trial = fillet(original, [original_edges[i] for i in trial_indices])
            if trial is not None:
                accepted = trial_indices
                accepted_shape = trial
        print(f"Subset order {order_number}: {len(accepted)}/{edge_count}")
        if len(accepted) > len(best_indices):
            best_indices = accepted
            best_shape = accepted_shape
        if len(best_indices) == edge_count:
            break

    if not best_indices:
        raise ValueError("Unable to construct any requested 0.2 mm rounds")

    result = best_shape
    explicit = set(best_indices)
    pending = [i for i in range(edge_count) if i not in explicit]

    # Apply remaining persistent carrier edges to the evolving solid. Edges
    # completely consumed by adjacent radius patches are handled below.
    for pass_number in range(1, 7):
        if not pending:
            break
        progress = False

        mapped = []
        mapped_indices = []
        for index in pending:
            edge, _ = matching_edge(result, original_edges[index])
            if edge is not None:
                mapped.append(edge)
                mapped_indices.append(index)

        if mapped:
            grouped = fillet(result, mapped)
            if grouped is not None:
                result = grouped
                explicit.update(mapped_indices)
                pending = [i for i in pending if i not in explicit]
                print(f"Pass {pass_number}: rounded {len(mapped_indices)} remaining carrier edges as a group")
                continue

        next_pending = []
        for index in pending:
            edge, _ = matching_edge(result, original_edges[index])
            if edge is None:
                next_pending.append(index)
                continue
            trial = fillet(result, [edge])
            if trial is not None:
                result = trial
                explicit.add(index)
                progress = True
                print(f"Pass {pass_number}: rounded persistent original EDGE {index}")
            else:
                next_pending.append(index)
        pending = next_pending
        if not progress:
            break

    # An original edge may cease to exist after its two adjacent rounds create
    # a common corner patch. Such an edge is geometrically consumed rather than
    # left sharp. Distinguish this from a persistent, unrounded carrier edge.
    consumed = set()
    persistent = []
    for index in pending:
        edge, error = matching_edge(result, original_edges[index])
        if edge is None:
            consumed.add(index)
        else:
            persistent.append((index, error))

    covered = explicit | consumed
    print(f"Explicitly rounded original edges: {len(explicit)}/{edge_count}")
    print(f"Original edges consumed by adjacent round patches: {len(consumed)}")
    if consumed:
        print(f"Consumed original edge indices: {sorted(consumed)}")

    if persistent:
        details = ", ".join(f"{i}(carrier error={e:.6g})" for i, e in persistent)
        raise ValueError(
            "The following original edges remain as persistent carriers but "
            f"could not be rounded at R=0.2 mm: {details}"
        )

    if len(covered) != edge_count:
        missing = sorted(set(range(edge_count)) - covered)
        raise ValueError(f"Unaccounted original edges: {missing}")
    if not valid_single(result):
        raise ValueError("Final result is not a valid single solid")

    print(f"All {edge_count} original edges are rounded or incorporated into adjacent R=0.2 mm corner patches")
    print(f"Result valid: {result.isValid()}")
    print(f"Result solids: {len(result.Solids())}")
    print(f"Result faces: {len(result.Faces())}")
    print(f"Result edges: {len(result.Edges())}")
    print(f"Result volume: {result.Volume():.6f} mm^3")

    return cq.Workplane(obj=result)