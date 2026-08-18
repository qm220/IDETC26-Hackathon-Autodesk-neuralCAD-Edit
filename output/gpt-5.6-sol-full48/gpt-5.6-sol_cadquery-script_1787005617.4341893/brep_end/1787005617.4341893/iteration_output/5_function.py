def my_cad_function(args):
    import os
    import math
    import cadquery as cq

    input_file = os.path.expanduser(args['input_file'])
    imported = cq.importers.importStep(input_file)
    base = imported.val()

    if len(base.Solids()) != 1:
        raise ValueError('Expected one solid in the input STEP')
    if not base.isValid():
        raise ValueError('Imported solid is invalid')

    radius = 0.2
    current = base
    bbox = base.BoundingBox()

    print('Input valid:', base.isValid(), flush=True)
    print('Input faces:', len(base.Faces()), flush=True)
    print('Input edges:', len(base.Edges()), flush=True)
    print('Input bbox: %.6f x %.6f x %.6f mm' %
          (bbox.xlen, bbox.ylen, bbox.zlen), flush=True)

    def acceptable(shape):
        try:
            return (shape is not None and shape.isValid() and
                    len(shape.Solids()) == 1 and len(shape.Edges()) > 0)
        except Exception:
            return False

    def adjacent_faces(shape, edge):
        result = []
        for face in shape.Faces():
            try:
                if any(edge.isSame(fe) for fe in face.Edges()):
                    result.append(face)
            except Exception:
                pass
        return result

    def unit_components(vector):
        length = math.sqrt(vector.x * vector.x +
                           vector.y * vector.y +
                           vector.z * vector.z)
        if length < 1.0e-12:
            raise ValueError('Zero-length normal')
        return vector.x / length, vector.y / length, vector.z / length

    def is_sharp_edge(shape, edge):
        faces = adjacent_faces(shape, edge)
        if len(faces) != 2:
            return False
        try:
            point = edge.Center()
            n1 = unit_components(faces[0].normalAt(point))
            n2 = unit_components(faces[1].normalAt(point))
            dot = n1[0] * n2[0] + n1[1] * n2[1] + n1[2] * n2[2]
            # Fillet boundaries are tangent and must not be filleted again.
            return abs(dot) < 0.995
        except Exception:
            # Preserve an edge as a candidate if normal evaluation is not
            # supported for one of its adjacent imported surfaces.
            return True

    def edge_key(edge):
        center = edge.Center()
        try:
            kind = edge.geomType()
        except Exception:
            kind = 'UNKNOWN'
        # Absolute x and y coordinates collect bilateral mirror copies into
        # one operation, preserving the source model's two symmetry planes.
        return (round(abs(center.x), 4),
                round(abs(center.y), 4),
                round(center.z, 4),
                round(edge.Length(), 4),
                str(kind))

    def internal_priority(edge):
        center = edge.Center()
        tol = 1.0e-4
        on_outer = (abs(abs(center.x) - 1.0) < tol or
                    abs(abs(center.y) - 3.0) < tol or
                    abs(center.z + 0.75) < tol)
        # Cavity and transition edges first, as requested in the operation
        # plan. Longer chains are processed before small corner remnants.
        return (1 if on_outer else 0, -edge.Length())

    # First retry the exact all-edge operation. This is retained because it
    # gives the best rolling-ball corner solution if the local kernel build
    # can resolve it.
    try:
        direct = current.fillet(radius, list(current.Edges()))
        if acceptable(direct):
            print('Exact simultaneous all-edge fillet succeeded.', flush=True)
            print('Applied radius: 0.200000 mm', flush=True)
            print('Output faces:', len(direct.Faces()), flush=True)
            print('Output edges:', len(direct.Edges()), flush=True)
            return cq.Workplane(obj=direct)
    except Exception as exc:
        print('Exact simultaneous fillet failed:', str(exc), flush=True)

    # Resolve competing blends as ordered exact-radius features. Each group
    # contains symmetry-related sharp edges. After every successful feature,
    # topology and candidate edges are recomputed; tangent boundaries created
    # by prior rounds are excluded.
    successful_features = 0
    max_features = 80

    while successful_features < max_features:
        sharp_edges = [e for e in current.Edges() if is_sharp_edge(current, e)]
        if not sharp_edges:
            break

        groups = {}
        for edge in sharp_edges:
            groups.setdefault(edge_key(edge), []).append(edge)

        ordered_groups = list(groups.values())
        ordered_groups.sort(key=lambda group: internal_priority(group[0]))
        made_progress = False

        for group in ordered_groups:
            try:
                candidate = current.fillet(radius, group)
                if acceptable(candidate):
                    current = candidate
                    successful_features += 1
                    made_progress = True
                    print('Fillet feature %d succeeded on %d symmetry-related edge(s)' %
                          (successful_features, len(group)), flush=True)
                    break
            except Exception:
                pass

        if not made_progress:
            break

    remaining = [e for e in current.Edges() if is_sharp_edge(current, e)]
    out_bbox = current.BoundingBox()
    print('Ordered exact-radius fillet features:', successful_features, flush=True)
    print('Remaining detected sharp edges:', len(remaining), flush=True)
    print('Output valid:', current.isValid(), flush=True)
    print('Output solids:', len(current.Solids()), flush=True)
    print('Output faces:', len(current.Faces()), flush=True)
    print('Output edges:', len(current.Edges()), flush=True)
    print('Output bbox: %.6f x %.6f x %.6f mm' %
          (out_bbox.xlen, out_bbox.ylen, out_bbox.zlen), flush=True)

    if successful_features == 0:
        print('No exact 0.2 mm partial fillet group could be resolved.', flush=True)
    elif remaining:
        print('Some sharp edges remain because their exact-radius blends could not be resolved in the current topology.', flush=True)
    else:
        print('All detected non-tangent edges have received exact 0.2 mm rounds.', flush=True)

    return cq.Workplane(obj=current)
