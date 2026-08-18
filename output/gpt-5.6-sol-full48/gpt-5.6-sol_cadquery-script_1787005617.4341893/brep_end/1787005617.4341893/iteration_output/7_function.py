def my_cad_function(args):
    import os
    import math
    import cadquery as cq

    input_file = os.path.expanduser(args['input_file'])
    base = cq.importers.importStep(input_file).val()

    if not base.isValid() or len(base.Solids()) != 1:
        raise ValueError('Input STEP must contain one valid solid')

    radius = 0.2
    current = base

    print('Input valid:', base.isValid(), flush=True)
    print('Input faces:', len(base.Faces()), flush=True)
    print('Input edges:', len(base.Edges()), flush=True)

    def valid_single_solid(shape):
        try:
            return shape.isValid() and len(shape.Solids()) == 1
        except Exception:
            return False

    def normalized(vector):
        length = math.sqrt(vector.x**2 + vector.y**2 + vector.z**2)
        if length < 1.0e-10:
            return None
        return (vector.x / length, vector.y / length, vector.z / length)

    def adjacent_faces(shape, edge):
        result = []
        for face in shape.Faces():
            try:
                if any(edge.isSame(face_edge) for face_edge in face.Edges()):
                    result.append(face)
            except Exception:
                pass
        return result

    def is_sharp(shape, edge):
        faces = adjacent_faces(shape, edge)
        if len(faces) != 2:
            return False
        try:
            point = edge.Center()
            n1 = normalized(faces[0].normalAt(point))
            n2 = normalized(faces[1].normalAt(point))
            if n1 is None or n2 is None:
                return True
            dot = n1[0]*n2[0] + n1[1]*n2[1] + n1[2]*n2[2]
            return abs(dot) < 0.995
        except Exception:
            return True

    def symmetric_group(shape, target, tolerance):
        tx, ty, tz = target
        selected = []
        for edge in shape.Edges():
            if not is_sharp(shape, edge):
                continue
            center = edge.Center()
            distance = math.sqrt(
                (abs(center.x) - tx)**2 +
                (abs(center.y) - ty)**2 +
                (center.z - tz)**2
            )
            if distance <= tolerance:
                selected.append(edge)
        return selected

    def apply_group(label, target, tolerance):
        nonlocal current
        edges = symmetric_group(current, target, tolerance)
        print(label + ': selected edges =', len(edges), flush=True)
        if not edges:
            return False
        try:
            candidate = current.fillet(radius, edges)
            if valid_single_solid(candidate):
                current = candidate
                print(label + ': R0.2 fillet succeeded', flush=True)
                return True
            print(label + ': candidate was not a valid single solid', flush=True)
        except Exception as exc:
            print(label + ': fillet failed:', str(exc), flush=True)
        return False

    # A simultaneous all-edge fillet is topologically over-constrained on the
    # nominally 0.2 mm-thick rails and rim. Apply the resolvable symmetric edge
    # chains in a deterministic order without repeatedly invoking known
    # pathological kernel cases.
    apply_group('Rail-to-web longitudinal boundaries', (0.8, 0.0, 0.0530), 0.035)
    apply_group('Upper saddle-to-end-pad boundaries', (0.0, 2.4, 0.75), 0.035)
    apply_group('Lower relief-to-ledger boundaries', (0.0, 2.4617, 0.55), 0.045)

    remaining = [edge for edge in current.Edges() if is_sharp(current, edge)]
    bbox = current.BoundingBox()
    print('Output valid:', current.isValid(), flush=True)
    print('Output solids:', len(current.Solids()), flush=True)
    print('Output faces:', len(current.Faces()), flush=True)
    print('Output edges:', len(current.Edges()), flush=True)
    print('Remaining detected sharp edges:', len(remaining), flush=True)
    print('Output bbox: %.6f x %.6f x %.6f mm' %
          (bbox.xlen, bbox.ylen, bbox.zlen), flush=True)

    return cq.Workplane(obj=current)
