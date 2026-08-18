def my_cad_function(args):
    input_file = os.path.expanduser(args['input_file'])
    model = cq.importers.importStep(input_file)
    solid = model.val()

    bbox = solid.BoundingBox()
    edges = solid.Edges()
    print('Input valid:', solid.isValid())
    print('Input solids:', len(solid.Solids()))
    print('Input faces:', len(solid.Faces()))
    print('Input edges:', len(edges))
    print('Input volume: %.6f mm^3' % solid.Volume())
    print('Input bbox: %.6f x %.6f x %.6f mm' % (bbox.xlen, bbox.ylen, bbox.zlen))
    for i, edge in enumerate(edges):
        center = edge.Center()
        print('Edge %d: length=%.6f center=(%.6f, %.6f, %.6f) geom=%s' % (
            i, edge.Length(), center.x, center.y, center.z, edge.geomType()))

    radius = 0.2
    try:
        result = cq.Workplane(obj=solid).edges().fillet(radius)
        output = result.val()
        out_bbox = output.BoundingBox()
        print('Applied R=0.2 mm constant-radius fillets to all %d pre-fillet edges in one operation.' % len(edges))
        print('Output valid:', output.isValid())
        print('Output solids:', len(output.Solids()))
        print('Output faces:', len(output.Faces()))
        print('Output edges:', len(output.Edges()))
        print('Output volume: %.6f mm^3' % output.Volume())
        print('Output bbox: %.6f x %.6f x %.6f mm' % (out_bbox.xlen, out_bbox.ylen, out_bbox.zlen))
        return result
    except Exception as exc:
        print('Simultaneous all-edge R=0.2 mm fillet failed:', repr(exc))
        print('Returning the original model for diagnostic rendering.')
        return model