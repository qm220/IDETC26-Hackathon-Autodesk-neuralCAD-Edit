def my_cad_function(args):
    import os
    import math
    import cadquery as cq

    input_file = os.path.expanduser(args['input_file'])
    base = cq.importers.importStep(input_file).val()
    radius = 0.2

    if not base.isValid() or len(base.Solids()) != 1:
        raise ValueError('Input STEP must contain one valid solid')

    def valid(shape):
        try:
            return shape.isValid() and len(shape.Solids()) == 1
        except Exception:
            return False

    def geom_type(edge):
        try:
            return str(edge.geomType())
        except Exception:
            return 'UNKNOWN'

    def dist(a, b):
        return math.sqrt((a.x-b.x)**2 + (a.y-b.y)**2 + (a.z-b.z)**2)

    def edge_descriptor(edge):
        c = edge.Center()
        return {
            'center': c,
            'length': edge.Length(),
            'type': geom_type(edge)
        }

    def symmetry_key(edge):
        c = edge.Center()
        return (
            round(abs(c.x), 3),
            round(abs(c.y), 3),
            round(c.z, 3),
            round(edge.Length(), 3),
            geom_type(edge)
        )

    original_edges = list(base.Edges())
    original_descriptors = [edge_descriptor(e) for e in original_edges]
    bbox0 = base.BoundingBox()

    print('Input valid:', base.isValid(), flush=True)
    print('Input solids:', len(base.Solids()), flush=True)
    print('Input faces:', len(base.Faces()), flush=True)
    print('Input edges:', len(original_edges), flush=True)

    # First try the literal requested operation as one rolling-ball feature.
    try:
        candidate = base.fillet(radius, original_edges)
        if valid(candidate):
            bb = candidate.BoundingBox()
            print('Simultaneous all-edge R0.2 fillet succeeded', flush=True)
            print('Output faces:', len(candidate.Faces()), flush=True)
            print('Output edges:', len(candidate.Edges()), flush=True)
            print('Output bbox: %.6f x %.6f x %.6f mm' %
                  (bb.xlen, bb.ylen, bb.zlen), flush=True)
            return cq.Workplane(obj=candidate)
        print('Simultaneous all-edge result was invalid', flush=True)
    except Exception as exc:
        print('Simultaneous all-edge fillet failed:', str(exc), flush=True)

    # Preserve the original symmetric edge families.  Matching against the
    # current body allows neighboring rounds to trim an edge without losing it.
    family_map = {}
    for index, edge in enumerate(original_edges):
        family_map.setdefault(symmetry_key(edge), []).append(index)

    families = list(family_map.values())

    # Internal cavity and saddle boundaries are processed before the outer
    # perimeter, as they are the most constrained by the thin shell geometry.
    def family_priority(indices):
        cs = [original_descriptors[i]['center'] for i in indices]
        ax = sum(abs(c.x) for c in cs) / len(cs)
        ay = sum(abs(c.y) for c in cs) / len(cs)
        az = sum(c.z for c in cs) / len(cs)
        outer = int(ax > 0.95 or ay > 2.95 or az < -0.70)
        return (outer, ax + ay / 3.0, az)

    families.sort(key=family_priority)
    current = base
    completed = set()

    def match_family(shape, indices, max_center_shift=0.38):
        available = list(shape.Edges())
        used = set()
        selected = []

        for index in indices:
            target = original_descriptors[index]
            best_j = None
            best_score = 1.0e9
            for j, edge in enumerate(available):
                if j in used:
                    continue
                c = edge.Center()
                dc = dist(c, target['center'])
                if dc > max_center_shift:
                    continue
                type_penalty = 0.0 if geom_type(edge) == target['type'] else 0.18
                length_error = abs(edge.Length() - target['length'])
                score = dc + 0.18 * length_error + type_penalty
                if score < best_score:
                    best_score = score
                    best_j = j
            if best_j is None:
                return []
            used.add(best_j)
            selected.append(available[best_j])
        return selected

    def attempt(label, indices):
        nonlocal current
        selected = match_family(current, indices)
        if len(selected) != len(indices):
            print(label + ': could not rematch all edges', flush=True)
            return False
        try:
            candidate = current.fillet(radius, selected)
            if valid(candidate):
                current = candidate
                print(label + ': R0.2 succeeded on %d edge(s)' % len(selected), flush=True)
                return True
            print(label + ': invalid result', flush=True)
        except Exception as exc:
            print(label + ': failed: ' + str(exc), flush=True)
        return False

    # Several passes allow a family that initially conflicts at a vertex to be
    # retried after its neighboring symmetric family has been rounded.
    for pass_number in range(3):
        progress = False
        print('Symmetric family pass:', pass_number + 1, flush=True)
        for family_number, indices in enumerate(families):
            key = tuple(indices)
            if key in completed:
                continue
            if attempt('Family %d' % family_number, indices):
                completed.add(key)
                progress = True
        if not progress:
            break

    # Retry unresolved edges in symmetric vertex-star groups.  Selecting all
    # edges meeting equivalent corners often lets OCC construct the required
    # corner blend where separate edge features cannot.
    unresolved = [f for f in families if tuple(f) not in completed]
    vertex_groups = {}
    for family in unresolved:
        for index in family:
            edge = original_edges[index]
            for vertex in edge.Vertices():
                p = vertex.Center()
                key = (round(abs(p.x), 3), round(abs(p.y), 3), round(p.z, 3))
                vertex_groups.setdefault(key, set()).add(index)

    stars = [sorted(indices) for indices in vertex_groups.values() if len(indices) > 1]
    stars.sort(key=lambda ids: family_priority(ids))
    for star_number, indices in enumerate(stars):
        if attempt('Symmetric vertex star %d' % star_number, indices):
            for family in families:
                if set(family).issubset(set(indices)):
                    completed.add(tuple(family))

    # Final retry of every still-unresolved original family after the corner
    # blends. No radius reduction or silent omission is performed.
    for family_number, indices in enumerate(families):
        key = tuple(indices)
        if key not in completed and attempt('Final family retry %d' % family_number, indices):
            completed.add(key)

    if not valid(current):
        raise ValueError('Fillet processing did not produce a valid single solid')

    bbox = current.BoundingBox()
    unresolved_count = sum(len(f) for f in families if tuple(f) not in completed)
    print('Successfully processed original edge families:', len(completed), '/', len(families), flush=True)
    print('Unresolved original edge references:', unresolved_count, flush=True)
    print('Output valid:', current.isValid(), flush=True)
    print('Output solids:', len(current.Solids()), flush=True)
    print('Output faces:', len(current.Faces()), flush=True)
    print('Output edges:', len(current.Edges()), flush=True)
    print('Output bbox: %.6f x %.6f x %.6f mm' %
          (bbox.xlen, bbox.ylen, bbox.zlen), flush=True)
    print('Bounding-box change: %.6g, %.6g, %.6g mm' %
          (bbox.xlen-bbox0.xlen, bbox.ylen-bbox0.ylen, bbox.zlen-bbox0.zlen), flush=True)

    return cq.Workplane(obj=current)
