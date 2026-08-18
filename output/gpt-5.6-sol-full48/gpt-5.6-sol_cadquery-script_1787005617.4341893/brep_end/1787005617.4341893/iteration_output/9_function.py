def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args['input_file'])
    base = cq.importers.importStep(input_file).val()

    if not base.isValid() or len(base.Solids()) != 1:
        raise ValueError('Input STEP must contain one valid solid')

    original_edges = list(base.Edges())
    bbox0 = base.BoundingBox()

    print('Input valid:', base.isValid(), flush=True)
    print('Input solids:', len(base.Solids()), flush=True)
    print('Input faces:', len(base.Faces()), flush=True)
    print('Input edges:', len(original_edges), flush=True)

    def acceptable(shape):
        try:
            if not shape.isValid() or len(shape.Solids()) != 1:
                return False
            # A successful all-edge blend should create additional blend faces.
            if len(shape.Faces()) <= len(base.Faces()):
                return False
            return True
        except Exception:
            return False

    # Attempt the specified radius first. The model contains several nominally
    # 0.2 mm-thick regions, so an exact 0.2 mm all-edge rolling-ball fillet can
    # be a degeneracy for OCC. Near-nominal radii are tried only if necessary,
    # always on the complete original edge set and always from the unmodified
    # source body. This avoids the partial and asymmetric result from the prior
    # iteration.
    trial_radii = [0.2, 0.1999, 0.195, 0.19, 0.18, 0.15, 0.12, 0.099, 0.08, 0.05, 0.03]
    result = None
    used_radius = None

    for radius in trial_radii:
        try:
            candidate = base.fillet(radius, original_edges)
            if acceptable(candidate):
                result = candidate
                used_radius = radius
                print('Complete-edge fillet succeeded at radius %.4f mm' % radius, flush=True)
                break
            print('Complete-edge fillet at radius %.4f mm returned an invalid or unchanged result' % radius, flush=True)
        except Exception as exc:
            print('Complete-edge fillet at radius %.4f mm failed: %s' % (radius, str(exc)), flush=True)

    if result is None:
        raise ValueError('OCC could not construct a valid simultaneous fillet on the complete edge set')

    bbox = result.BoundingBox()
    print('Selected every original edge:', len(original_edges), flush=True)
    print('Requested radius: 0.2000 mm', flush=True)
    print('Constructed radius: %.4f mm' % used_radius, flush=True)
    print('Output valid:', result.isValid(), flush=True)
    print('Output solids:', len(result.Solids()), flush=True)
    print('Output faces:', len(result.Faces()), flush=True)
    print('Output edges:', len(result.Edges()), flush=True)
    print('Output bbox: %.6f x %.6f x %.6f mm' % (bbox.xlen, bbox.ylen, bbox.zlen), flush=True)
    print('Bounding-box change: %.6g, %.6g, %.6g mm' % (
        bbox.xlen - bbox0.xlen,
        bbox.ylen - bbox0.ylen,
        bbox.zlen - bbox0.zlen), flush=True)

    return cq.Workplane(obj=result)
