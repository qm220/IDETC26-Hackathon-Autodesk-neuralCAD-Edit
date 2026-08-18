def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args['input_file'])
    imported = cq.importers.importStep(input_file)
    base = imported.val()

    solids = base.Solids()
    if len(solids) != 1:
        raise ValueError('Expected one solid in the input STEP; found %d' % len(solids))
    if not base.isValid():
        raise ValueError('The imported solid is invalid')

    edges = list(base.Edges())
    bbox = base.BoundingBox()
    print('Input solid valid:', base.isValid(), flush=True)
    print('Input faces:', len(base.Faces()), flush=True)
    print('Input edges:', len(edges), flush=True)
    print('Input bbox: %.6f x %.6f x %.6f mm' % (bbox.xlen, bbox.ylen, bbox.zlen), flush=True)

    def acceptable(shape):
        return (shape is not None and shape.isValid() and
                len(shape.Solids()) == 1 and len(shape.Edges()) > 0)

    # Apply one rolling-ball fillet feature to the complete unique edge set.
    # Exact 0.2 mm is always attempted first.
    radii = [0.2, 0.199999, 0.1999, 0.199]
    errors = []
    for radius in radii:
        try:
            result = base.fillet(radius, edges)
            if acceptable(result):
                out_bbox = result.BoundingBox()
                print('All-edge fillet succeeded.', flush=True)
                print('Applied radius: %.6f mm' % radius, flush=True)
                print('Output faces:', len(result.Faces()), flush=True)
                print('Output edges:', len(result.Edges()), flush=True)
                print('Output solids:', len(result.Solids()), flush=True)
                print('Output valid:', result.isValid(), flush=True)
                print('Output bbox: %.6f x %.6f x %.6f mm' %
                      (out_bbox.xlen, out_bbox.ylen, out_bbox.zlen), flush=True)
                return cq.Workplane(obj=result)
            errors.append('R=%.6f produced an invalid result' % radius)
        except Exception as exc:
            errors.append('R=%.6f: %s' % (radius, str(exc)))

    print('Simultaneous all-edge fillet attempts failed:', flush=True)
    for message in errors:
        print(message, flush=True)

    # Return the valid source body so the execution still produces diagnostic
    # views. No partial fillet is returned because that would falsely imply
    # that every requested edge had been rounded.
    print('Returning unchanged input for diagnosis.', flush=True)
    return cq.Workplane(obj=base)