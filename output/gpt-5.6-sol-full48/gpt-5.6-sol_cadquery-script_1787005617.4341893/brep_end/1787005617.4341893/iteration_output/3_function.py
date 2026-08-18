def my_cad_function(args):
    import os
    import random
    import itertools
    import cadquery as cq

    requested_radius = 0.2
    input_file = os.path.expanduser(args['input_file'])
    base = cq.importers.importStep(input_file).val()

    if not base.isValid() or len(base.Solids()) != 1:
        raise ValueError('Input STEP must contain one valid solid')

    original_edges = list(base.Edges())
    print('Input valid:', base.isValid())
    print('Input solids:', len(base.Solids()))
    print('Input faces:', len(base.Faces()))
    print('Input edges:', len(original_edges))

    def valid(shape):
        return shape is not None and shape.isValid() and len(shape.Solids()) == 1

    # First request the exact operation directly from OCCT.
    try:
        result = base.fillet(requested_radius, original_edges)
        if valid(result):
            print('Exact simultaneous all-edge R=0.2 mm fillet succeeded.')
            return cq.Workplane(obj=result)
    except Exception as exc:
        print('Exact simultaneous all-edge fillet failed:', repr(exc))

    descriptors = []
    for edge_id, edge in enumerate(original_edges):
        center = edge.Center()
        vertices = []
        for vertex in edge.Vertices():
            p = vertex.Center()
            vertices.append((p.x, p.y, p.z))
        descriptors.append({
            'id': edge_id,
            'center': (center.x, center.y, center.z),
            'length': edge.Length(),
            'geom': edge.geomType(),
            'vertices': vertices
        })

    def distance(a, b):
        return ((a[0] - b[0]) ** 2 +
                (a[1] - b[1]) ** 2 +
                (a[2] - b[2]) ** 2) ** 0.5

    # Build exact bilateral symmetry orbits from the untouched model.
    remaining = set(range(len(descriptors)))
    orbits = []
    while remaining:
        seed_id = min(remaining)
        seed = descriptors[seed_id]
        x, y, z = seed['center']
        targets = ((x, y, z), (-x, y, z), (x, -y, z), (-x, -y, z))
        orbit = set()
        for target in targets:
            candidates = []
            for candidate_id in remaining:
                candidate = descriptors[candidate_id]
                if candidate['geom'] != seed['geom']:
                    continue
                score = distance(candidate['center'], target)
                score += 0.02 * abs(candidate['length'] - seed['length'])
                candidates.append((score, candidate_id))
            if candidates:
                score, candidate_id = min(candidates)
                if score < 1.0e-5:
                    orbit.add(candidate_id)
        if not orbit:
            orbit.add(seed_id)
        remaining -= orbit
        orbits.append(tuple(sorted(orbit)))

    print('Symmetry edge orbits:', orbits)

    def endpoint_score(desc, edge):
        current_vertices = []
        for vertex in edge.Vertices():
            p = vertex.Center()
            current_vertices.append((p.x, p.y, p.z))
        if not desc['vertices'] or not current_vertices:
            return 0.0
        # Adjacent fillets trim an original edge, so only penalize endpoints
        # by their distance to the original supporting edge endpoints.
        total = 0.0
        for point in current_vertices:
            total += min(distance(point, q) for q in desc['vertices'])
        return total / len(current_vertices)

    def edge_score(desc, edge):
        if edge.geomType() != desc['geom']:
            return 1.0e9
        c = edge.Center()
        center = (c.x, c.y, c.z)
        score = distance(center, desc['center'])
        score += 0.025 * abs(edge.Length() - desc['length'])
        score += 0.05 * endpoint_score(desc, edge)
        return score

    def locate_edges(shape, edge_ids):
        available = list(enumerate(shape.Edges()))
        selected = []
        used = set()
        for edge_id in edge_ids:
            desc = descriptors[edge_id]
            ranked = sorted(
                (edge_score(desc, edge), index, edge)
                for index, edge in available if index not in used
            )
            if not ranked or ranked[0][0] > 0.48:
                return None
            _, index, edge = ranked[0]
            used.add(index)
            selected.append(edge)
        return selected

    def apply_orbit(shape, orbit, radius):
        selected = locate_edges(shape, orbit)
        if selected:
            try:
                trial = shape.fillet(radius, selected)
                if valid(trial):
                    return trial, 'simultaneous'
            except Exception:
                pass

        # Preserve symmetry transactionally even when the orbit must be
        # resolved as multiple OCCT fillet features.
        if len(orbit) <= 4:
            orderings = list(itertools.permutations(orbit))
        else:
            orderings = [orbit, tuple(reversed(orbit))]

        for ordering in orderings:
            trial = shape
            successful = True
            for edge_id in ordering:
                selected = locate_edges(trial, (edge_id,))
                if not selected:
                    successful = False
                    break
                try:
                    next_shape = trial.fillet(radius, selected)
                    if not valid(next_shape):
                        successful = False
                        break
                    trial = next_shape
                except Exception:
                    successful = False
                    break
            if successful:
                return trial, 'sequential'
        return None, None

    # Determine which exact-radius orbits are independently feasible. This is
    # also useful diagnostic information for geometrically crowded edges.
    independently_feasible = []
    independently_blocked = []
    for orbit in orbits:
        trial, method = apply_orbit(base, orbit, requested_radius)
        if trial is None:
            independently_blocked.append(orbit)
        else:
            independently_feasible.append(orbit)
    print('Independently feasible exact-radius orbits:', independently_feasible)
    print('Independently blocked exact-radius orbits:', independently_blocked)

    def orbit_key(orbit):
        points = [descriptors[i]['center'] for i in orbit]
        z = sum(p[2] for p in points) / len(points)
        x = sum(abs(p[0]) for p in points) / len(points)
        y = sum(abs(p[1]) for p in points) / len(points)
        return (z, x, y, min(orbit))

    orders = [
        sorted(orbits, key=orbit_key),
        sorted(orbits, key=orbit_key, reverse=True),
        sorted(orbits, key=lambda o: (orbit_key(o)[1], orbit_key(o)[2], orbit_key(o)[0])),
        sorted(orbits, key=lambda o: (-orbit_key(o)[1], -orbit_key(o)[2], orbit_key(o)[0])),
        sorted(orbits, key=lambda o: (abs(orbit_key(o)[0]), orbit_key(o)[2], orbit_key(o)[1]))
    ]

    # Explore deterministic randomized feature orders. Fillets at intersecting
    # vertices are highly order-dependent in OCCT.
    rng = random.Random(332032)
    for _ in range(55):
        order = list(orbits)
        rng.shuffle(order)
        orders.append(order)

    best_shape = base
    best_done = set()
    best_log = []

    for strategy_index, order in enumerate(orders):
        current = base
        done = set()
        log = []
        pending = list(order)

        for pass_index in range(5):
            progressed = False
            deferred = []
            for orbit in pending:
                trial, method = apply_orbit(current, orbit, requested_radius)
                if trial is None:
                    deferred.append(orbit)
                else:
                    current = trial
                    done.update(orbit)
                    log.append((orbit, method, pass_index + 1))
                    progressed = True
            pending = deferred
            if not progressed or not pending:
                break

        if len(done) > len(best_done):
            best_shape = current
            best_done = set(done)
            best_log = list(log)
            print('New best exact strategy:', strategy_index + 1,
                  'rounded', len(best_done), '/', len(original_edges))

        if len(done) == len(original_edges):
            print('All original edges rounded at exact R=0.2 mm.')
            return cq.Workplane(obj=current)

    # Try a tolerance-level reduction only as a final kernel workaround. The
    # difference is one nanometre and does not intentionally change the
    # specified engineering radius.
    tolerance_radius = requested_radius - 1.0e-6
    try:
        tolerance_result = base.fillet(tolerance_radius, original_edges)
        if valid(tolerance_result):
            print('All-edge fillet succeeded at tolerance-equivalent radius:',
                  tolerance_radius)
            return cq.Workplane(obj=tolerance_result)
    except Exception as exc:
        print('Tolerance-equivalent simultaneous fillet failed:', repr(exc))

    missing = sorted(set(range(len(original_edges))) - best_done)
    bbox = best_shape.BoundingBox()
    print('Chosen exact-radius transaction log:', best_log)
    print('Rounded original edge IDs:', sorted(best_done))
    print('Unresolved original edge IDs:', missing)
    print('Output valid:', best_shape.isValid())
    print('Output solids:', len(best_shape.Solids()))
    print('Output faces:', len(best_shape.Faces()))
    print('Output edges:', len(best_shape.Edges()))
    print('Output volume: %.6f mm^3' % best_shape.Volume())
    print('Output bbox: %.6f x %.6f x %.6f mm' %
          (bbox.xlen, bbox.ylen, bbox.zlen))
    print('Exact all-edge operation remains incomplete; returning the most complete symmetric result.')
    return cq.Workplane(obj=best_shape)