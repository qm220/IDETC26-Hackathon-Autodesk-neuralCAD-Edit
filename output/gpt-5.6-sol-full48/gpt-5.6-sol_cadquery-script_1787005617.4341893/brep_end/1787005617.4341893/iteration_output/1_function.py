def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args['input_file'])
    model = cq.importers.importStep(input_file)
    solid = model.val()
    radius = 0.2

    original_edges = list(solid.Edges())
    print('Input valid:', solid.isValid())
    print('Input solids:', len(solid.Solids()))
    print('Input faces:', len(solid.Faces()))
    print('Input edges:', len(original_edges))

    # Record persistent geometric descriptors for the 36 pre-fillet edges.
    descriptors = []
    for i, edge in enumerate(original_edges):
        c = edge.Center()
        descriptors.append({
            'id': i,
            'center': (c.x, c.y, c.z),
            'length': edge.Length(),
            'geom': edge.geomType()
        })

    # Symmetric edge groups, ordered with hidden cavity/relief edges first and
    # external perimeter edges last. Each initial edge occurs exactly once.
    groups = [
        ('lower relief longitudinal boundaries', [0, 2]),
        ('lower relief transverse boundaries', [1, 3]),
        ('underside transition side segments', [4, 6, 7, 9]),
        ('internal upper transverse ledges', [5, 8]),
        ('internal end-wall vertical edges', [10, 12, 13, 15]),
        ('inner bottom longitudinal rim edges', [11, 14]),
        ('inner bottom transverse rim edges', [16, 17]),
        ('upper saddle transverse boundaries', [18, 20]),
        ('upper saddle side boundaries', [19, 21]),
        ('upper end-pad side edges', [22, 24, 25, 27]),
        ('upper external transverse edges', [23, 26]),
        ('external vertical corner edges', [28, 30, 34, 35]),
        ('outer bottom longitudinal edges', [29, 32]),
        ('outer bottom transverse edges', [31, 33])
    ]

    def edge_score(desc, edge):
        c = edge.Center()
        dx = c.x - desc['center'][0]
        dy = c.y - desc['center'][1]
        dz = c.z - desc['center'][2]
        center_error = (dx * dx + dy * dy + dz * dz) ** 0.5
        length_error = abs(edge.Length() - desc['length'])
        geom_penalty = 0.0 if edge.geomType() == desc['geom'] else 1000.0
        return geom_penalty + center_error + 0.08 * length_error

    def map_edges(shape, ids):
        available = list(shape.Edges())
        selected = []
        used = set()
        for edge_id in ids:
            desc = descriptors[edge_id]
            ranked = sorted(
                ((edge_score(desc, edge), j, edge) for j, edge in enumerate(available) if j not in used),
                key=lambda item: item[0]
            )
            if not ranked:
                raise RuntimeError('No current edge available for original edge %d' % edge_id)
            score, j, edge = ranked[0]
            if score >= 1000.0:
                raise RuntimeError('No matching geometry remains for original edge %d' % edge_id)
            used.add(j)
            selected.append(edge)
        return selected

    # First report whether each edge is intrinsically filletable on the
    # untouched input. This distinguishes local radius conflicts from conflicts
    # caused only by simultaneous corner resolution.
    individually_failed = []
    for i, edge in enumerate(original_edges):
        try:
            test = solid.fillet(radius, [edge])
            if not test.isValid() or len(test.Solids()) != 1:
                individually_failed.append(i)
        except Exception:
            individually_failed.append(i)
    print('Original edges that fail an isolated R=0.2 mm fillet:', individually_failed)

    current = solid
    completed = []
    pending = list(groups)

    # Multiple passes permit groups initially blocked by a multi-edge corner to
    # succeed after neighboring rounds have established rolling-ball blends.
    for pass_number in range(3):
        if not pending:
            break
        next_pending = []
        progress = False
        print('Sequential fillet pass:', pass_number + 1)
        for label, ids in pending:
            try:
                selected = map_edges(current, ids)
                trial = current.fillet(radius, selected)
                if not trial.isValid() or len(trial.Solids()) != 1:
                    raise RuntimeError('fillet produced an invalid or non-single solid')
                current = trial
                completed.extend(ids)
                progress = True
                print('Applied R=0.2 mm to %s, original edges %s' % (label, ids))
            except Exception as exc:
                next_pending.append((label, ids))
                print('Deferred %s, original edges %s: %r' % (label, ids, exc))
        pending = next_pending
        if not progress:
            break

    completed = sorted(set(completed))
    missing = sorted(set(range(len(original_edges))) - set(completed))
    bbox = current.BoundingBox()
    print('Successfully processed original edge IDs:', completed)
    print('Unresolved original edge IDs:', missing)
    print('Output valid:', current.isValid())
    print('Output solids:', len(current.Solids()))
    print('Output faces:', len(current.Faces()))
    print('Output edges:', len(current.Edges()))
    print('Output volume: %.6f mm^3' % current.Volume())
    print('Output bbox: %.6f x %.6f x %.6f mm' % (bbox.xlen, bbox.ylen, bbox.zlen))

    if not missing:
        print('All 36 pre-fillet edges received constant-radius R=0.2 mm rounds.')
    else:
        print('Partial diagnostic result returned; remaining edge groups require further ordering analysis.')

    return cq.Workplane(obj=current)
