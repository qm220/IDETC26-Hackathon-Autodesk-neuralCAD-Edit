def my_cad_function(args):
    import os
    import math
    import cadquery as cq

    input_file = os.path.expanduser(args['input_file'])
    base = cq.importers.importStep(input_file).val()

    if len(base.Solids()) != 1 or not base.isValid():
        raise ValueError('Input STEP must contain one valid solid')

    radius = 0.2
    current = base

    print('Input valid:', base.isValid(), flush=True)
    print('Input faces:', len(base.Faces()), flush=True)
    print('Input edges:', len(base.Edges()), flush=True)

    def valid_solid(shape):
        try:
            return shape.isValid() and len(shape.Solids()) == 1
        except Exception:
            return False

    def adjacent_faces(shape, edge):
        found = []
        for face in shape.Faces():
            try:
                if any(edge.isSame(fe) for fe in face.Edges()):
                    found.append(face)
            except Exception:
                pass
        return found

    def normalized(v):
        length = math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z)
        if length < 1.0e-10:
            return None
        return (v.x / length, v.y / length, v.z / length)

    def is_sharp(shape, edge):
        faces = adjacent_faces(shape, edge)
        if len(faces) != 2:
            return False
        try:
            p = edge.Center()
            n1 = normalized(faces[0].normalAt(p))
            n2 = normalized(faces[1].normalAt(p))
            if n1 is None or n2 is None:
                return True
            dot = n1[0] * n2[0] + n1[1] * n2[1] + n1[2] * n2[2]
            return abs(dot) < 0.995
        except Exception:
            return True

    def symmetry_key(edge):
        c = edge.Center()
        try:
            geometry = edge.geomType()
        except Exception:
            geometry = 'UNKNOWN'
        return (round(abs(c.x), 4), round(abs(c.y), 4),
                round(c.z, 4), round(edge.Length(), 4), str(geometry))

    def priority(group):
        edge = group[0]
        c = edge.Center()
        outer = (abs(abs(c.x) - 1.0) < 1.0e-3 or
                 abs(abs(c.y) - 3.0) < 1.0e-3 or
                 abs(c.z + 0.75) < 1.0e-3)
        return (1 if outer else 0, -edge.Length())

    # First test the literal one-feature all-edge operation.
    try:
        result = current.fillet(radius, list(current.Edges()))
        if valid_solid(result):
            print('Simultaneous all-edge R0.2 fillet succeeded.', flush=True)
            print('Output faces:', len(result.Faces()), flush=True)
            print('Output edges:', len(result.Edges()), flush=True)
            return cq.Workplane(obj=result)
    except Exception as exc:
        print('Simultaneous all-edge fillet failed:', str(exc), flush=True)

    # Apply exact-radius symmetric groups in a bounded staged process. The
    # strict limits prevent pathological OCCT fillet attempts from preventing
    # the edited solid from being returned for inspection.
    successes = 0
    total_attempts = 0
    max_successes = 12
    max_total_attempts = 24
    max_failed_attempts_per_stage = 6

    while successes < max_successes and total_attempts < max_total_attempts:
        sharp = [e for e in current.Edges() if is_sharp(current, e)]
        groups_by_key = {}
        for edge in sharp:
            groups_by_key.setdefault(symmetry_key(edge), []).append(edge)

        groups = sorted(groups_by_key.values(), key=priority)
        if not groups:
            break

        progressed = False
        failed_this_stage = 0

        for group in groups:
            if total_attempts >= max_total_attempts:
                break
            total_attempts += 1

            c = group[0].Center()
            print('Trying group at |x|=%.4f |y|=%.4f z=%.4f, count=%d' %
                  (abs(c.x), abs(c.y), c.z, len(group)), flush=True)
            try:
                candidate = current.fillet(radius, group)
                if valid_solid(candidate):
                    current = candidate
                    successes += 1
                    progressed = True
                    print('Feature %d succeeded.' % successes, flush=True)
                    break
            except Exception:
                pass

            failed_this_stage += 1
            if failed_this_stage >= max_failed_attempts_per_stage:
                break

        if not progressed:
            break

    remaining = [e for e in current.Edges() if is_sharp(current, e)]
    bbox = current.BoundingBox()
    print('Successful exact R0.2 fillet features:', successes, flush=True)
    print('Bounded fillet attempts:', total_attempts, flush=True)
    print('Remaining detected sharp edges:', len(remaining), flush=True)
    print('Output valid:', current.isValid(), flush=True)
    print('Output solids:', len(current.Solids()), flush=True)
    print('Output faces:', len(current.Faces()), flush=True)
    print('Output edges:', len(current.Edges()), flush=True)
    print('Output bbox: %.6f x %.6f x %.6f mm' %
          (bbox.xlen, bbox.ylen, bbox.zlen), flush=True)

    return cq.Workplane(obj=current)
