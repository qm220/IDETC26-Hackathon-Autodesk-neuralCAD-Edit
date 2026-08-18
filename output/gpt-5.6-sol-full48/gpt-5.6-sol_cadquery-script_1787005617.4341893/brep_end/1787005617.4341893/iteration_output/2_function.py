def my_cad_function(args):
    import os
    import itertools
    import cadquery as cq

    radius = 0.2
    input_file = os.path.expanduser(args['input_file'])
    imported = cq.importers.importStep(input_file)
    base = imported.val()
    original_edges = list(base.Edges())

    print('Input valid:', base.isValid())
    print('Input solids:', len(base.Solids()))
    print('Input faces:', len(base.Faces()))
    print('Input edges:', len(original_edges))

    if not base.isValid() or len(base.Solids()) != 1:
        raise ValueError('The input STEP must contain one valid solid')

    # First try the semantically exact operation: one rolling-ball fillet
    # containing the complete pre-fillet edge set.
    try:
        direct = base.fillet(radius, original_edges)
        if direct.isValid() and len(direct.Solids()) == 1:
            print('Complete all-edge R=0.2 mm fillet succeeded in one operation.')
            return cq.Workplane(obj=direct)
    except Exception as exc:
        print('Single-feature all-edge fillet failed:', repr(exc))

    descriptors = []
    for i, edge in enumerate(original_edges):
        c = edge.Center()
        vertices = edge.Vertices()
        endpoints = []
        for vertex in vertices:
            p = vertex.Center()
            endpoints.append((p.x, p.y, p.z))
        descriptors.append({
            'id': i,
            'center': (c.x, c.y, c.z),
            'length': edge.Length(),
            'geom': edge.geomType(),
            'endpoints': endpoints
        })

    def reflected_distance(a, b):
        return ((a[0] - b[0]) ** 2 +
                (a[1] - b[1]) ** 2 +
                (a[2] - b[2]) ** 2) ** 0.5

    # Form complete symmetry orbits under x=0 and y=0 reflections. Fillet
    # transactions are committed only when the entire orbit succeeds, so no
    # asymmetric partial result can be retained.
    unused = set(range(len(descriptors)))
    orbits = []
    while unused:
        seed_id = min(unused)
        seed = descriptors[seed_id]
        sx, sy, sz = seed['center']
        targets = [
            (sx, sy, sz), (-sx, sy, sz),
            (sx, -sy, sz), (-sx, -sy, sz)
        ]
        orbit = set()
        for target in targets:
            candidates = []
            for j in unused:
                d = descriptors[j]
                if d['geom'] != seed['geom']:
                    continue
                length_error = abs(d['length'] - seed['length'])
                center_error = reflected_distance(d['center'], target)
                candidates.append((center_error + 0.1 * length_error, j))
            if candidates:
                score, j = min(candidates)
                if score < 1.0e-4:
                    orbit.add(j)
        if not orbit:
            orbit.add(seed_id)
        unused -= orbit
        orbits.append(sorted(orbit))

    print('Symmetry edge orbits:', orbits)

    def edge_score(desc, edge):
        if edge.geomType() != desc['geom']:
            return 1.0e6
        c = edge.Center()
        dc = ((c.x - desc['center'][0]) ** 2 +
              (c.y - desc['center'][1]) ** 2 +
              (c.z - desc['center'][2]) ** 2) ** 0.5
        dl = abs(edge.Length() - desc['length'])
        # Original edges can be trimmed by adjacent rounds, so position is
        # weighted more strongly than retained length.
        return dc + 0.04 * dl

    def map_one(shape, edge_id, blocked=None):
        if blocked is None:
            blocked = set()
        desc = descriptors[edge_id]
        ranked = []
        for j, edge in enumerate(shape.Edges()):
            if j in blocked:
                continue
            ranked.append((edge_score(desc, edge), j, edge))
        if not ranked:
            raise RuntimeError('No edge candidates remain for original edge %d' % edge_id)
        score, index, edge = min(ranked, key=lambda item: item[0])
        if score > 0.45:
            raise RuntimeError('Original edge %d is no longer identifiable (score %.6f)' % (edge_id, score))
        return edge, index

    def valid_single_solid(shape):
        return shape.isValid() and len(shape.Solids()) == 1

    def apply_orbit(shape, orbit):
        # Prefer one simultaneous feature for correct rolling-ball corner
        # resolution.
        try:
            selected = []
            blocked = set()
            for edge_id in orbit:
                edge, index = map_one(shape, edge_id, blocked)
                selected.append(edge)
                blocked.add(index)
            trial = shape.fillet(radius, selected)
            if valid_single_solid(trial):
                return trial, 'simultaneous'
        except Exception:
            pass

        # If simultaneous resolution fails, try every ordering within the
        # symmetry orbit, but commit only if every member succeeds.
        permutations = list(itertools.permutations(orbit))
        for ordering in permutations:
            trial = shape
            ok = True
            for edge_id in ordering:
                try:
                    edge, unused_index = map_one(trial, edge_id)
                    next_shape = trial.fillet(radius, [edge])
                    if not valid_single_solid(next_shape):
                        ok = False
                        break
                    trial = next_shape
                except Exception:
                    ok = False
                    break
            if ok:
                return trial, 'sequential-' + str(ordering)
        return None, None

    # Explore several feature orders from the untouched solid. Narrow hidden
    # cavity edges and high-valence transitions are sensitive to operation
    # order in OCCT.
    def orbit_key(orbit):
        centers = [descriptors[i]['center'] for i in orbit]
        z = sum(p[2] for p in centers) / len(centers)
        ax = sum(abs(p[0]) for p in centers) / len(centers)
        ay = sum(abs(p[1]) for p in centers) / len(centers)
        return z, ax, ay, min(orbit)

    orders = []
    orders.append(sorted(orbits, key=orbit_key))
    orders.append(sorted(orbits, key=orbit_key, reverse=True))
    orders.append(sorted(orbits, key=lambda o: (orbit_key(o)[1], orbit_key(o)[2], orbit_key(o)[0])))
    orders.append(sorted(orbits, key=lambda o: (-orbit_key(o)[1], -orbit_key(o)[2], orbit_key(o)[0])))
    orders.append(sorted(orbits, key=lambda o: (abs(orbit_key(o)[0]), orbit_key(o)[1], orbit_key(o)[2])))
    orders.append(list(orbits))
    orders.append(list(reversed(orbits)))

    best_shape = base
    best_done = set()
    best_log = []

    for strategy_index, ordered_orbits in enumerate(orders):
        current = base
        done = set()
        log = []
        pending = list(ordered_orbits)

        # Deferred passes allow a previously blocked orbit to become possible
        # after adjacent blends have been generated.
        for pass_index in range(4):
            progress = False
            next_pending = []
            for orbit in pending:
                result, method = apply_orbit(current, orbit)
                if result is not None:
                    current = result
                    done.update(orbit)
                    log.append((orbit, method, pass_index + 1))
                    progress = True
                else:
                    next_pending.append(orbit)
            pending = next_pending
            if not progress or not pending:
                break

        print('Strategy %d processed %d/%d original edges' %
              (strategy_index + 1, len(done), len(original_edges)))
        print('Strategy log:', log)

        if len(done) > len(best_done):
            best_shape = current
            best_done = set(done)
            best_log = list(log)
        if len(done) == len(original_edges):
            best_shape = current
            best_done = set(done)
            best_log = list(log)
            break

    missing = sorted(set(range(len(original_edges))) - best_done)
    bbox = best_shape.BoundingBox()
    print('Chosen transaction log:', best_log)
    print('Successfully rounded original edge IDs:', sorted(best_done))
    print('Unresolved original edge IDs:', missing)
    print('Output valid:', best_shape.isValid())
    print('Output solids:', len(best_shape.Solids()))
    print('Output faces:', len(best_shape.Faces()))
    print('Output edges:', len(best_shape.Edges()))
    print('Output volume: %.6f mm^3' % best_shape.Volume())
    print('Output bbox: %.6f x %.6f x %.6f mm' %
          (bbox.xlen, bbox.ylen, bbox.zlen))

    if missing:
        print('Exact R=0.2 mm all-edge result remains incomplete; no asymmetric orbit was committed.')
    else:
        print('All pre-fillet edges received exact constant-radius R=0.2 mm rounds.')

    return cq.Workplane(obj=best_shape)