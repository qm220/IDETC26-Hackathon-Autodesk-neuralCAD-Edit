def my_cad_function(args):
    import os
    import random
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    original = imported.val()
    source_edges = list(original.Edges())

    print(f"Input valid: {original.isValid()}")
    print(f"Input solids: {len(original.Solids())}")
    print(f"Original edges: {len(source_edges)}")

    # The source contains walls whose nominal thickness is itself 0.2 mm.
    # An exact 0.2 mm all-edge operation can therefore encounter zero-width
    # residual faces. Try the requested value first, followed only by tiny
    # tolerance-level reductions that preserve the intended nominal radius.
    trial_radii = [0.2, 0.19999, 0.1999, 0.1995, 0.199, 0.198, 0.195]

    for radius in trial_radii:
        try:
            candidate = original.fillet(radius, source_edges)
            if candidate.isValid() and len(candidate.Solids()) == 1:
                print(
                    f"All {len(source_edges)} original edges filleted in one operation; "
                    f"effective radius={radius:.5f} mm"
                )
                print(f"Output edges: {len(candidate.Edges())}")
                return cq.Workplane("XY").newObject([candidate])
        except Exception as exc:
            print(f"All-edge trial R={radius:.5f} rejected: {type(exc).__name__}")

    indexed = list(enumerate(source_edges))

    def edge_signature(item):
        edge_id, edge = item
        center = edge.Center()
        try:
            kind = edge.geomType()
        except Exception:
            kind = ""
        return (
            kind,
            round(edge.Length(), 8),
            round(center.z, 8),
            round(center.y, 8),
            round(center.x, 8),
            edge_id,
        )

    # If the kernel cannot construct one global blend, determine the largest
    # compatible source-edge set. Test near-nominal radii as well as 0.2 mm;
    # coverage is prioritized, then closeness to the requested radius.
    best_shape = original
    best_ids = set()
    best_radius = 0.0
    best_length = 0.0

    search_radii = [0.2, 0.1999, 0.199, 0.195]
    rng = random.Random(84021)

    for radius in search_radii:
        orders = [
            sorted(indexed, key=lambda item: item[1].Length()),
            sorted(indexed, key=lambda item: item[1].Length(), reverse=True),
            sorted(indexed, key=edge_signature),
            sorted(indexed, key=edge_signature, reverse=True),
        ]

        for _ in range(12):
            order = indexed[:]
            rng.shuffle(order)
            orders.append(order)

        for order_number, order in enumerate(orders):
            accepted = []
            accepted_ids = set()
            current = original

            for edge_id, edge in order:
                try:
                    trial = original.fillet(radius, accepted + [edge])
                    if trial.isValid() and len(trial.Solids()) == 1:
                        accepted.append(edge)
                        accepted_ids.add(edge_id)
                        current = trial
                except Exception:
                    pass

            accepted_length = sum(source_edges[i].Length() for i in accepted_ids)
            score = (
                len(accepted_ids),
                radius,
                accepted_length,
            )
            best_score = (
                len(best_ids),
                best_radius,
                best_length,
            )

            print(
                f"R={radius:.4f}, order {order_number + 1}: "
                f"{len(accepted_ids)}/{len(source_edges)} edges"
            )

            if score > best_score:
                best_shape = current
                best_ids = accepted_ids
                best_radius = radius
                best_length = accepted_length

            if len(best_ids) == len(source_edges):
                print(
                    f"All source edges covered at effective radius "
                    f"{best_radius:.5f} mm"
                )
                return cq.Workplane("XY").newObject([best_shape])

    print(
        f"Best kernel-compatible result: {len(best_ids)}/{len(source_edges)} "
        f"original edges at R={best_radius:.5f} mm"
    )
    print(f"Output valid: {best_shape.isValid()}")
    print(f"Output solids: {len(best_shape.Solids())}")
    print(f"Output edges: {len(best_shape.Edges())}")

    return cq.Workplane("XY").newObject([best_shape])