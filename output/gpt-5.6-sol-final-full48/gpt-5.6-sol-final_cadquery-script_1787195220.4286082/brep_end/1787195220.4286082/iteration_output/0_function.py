def my_cad_function(args):
    input_file = os.path.expanduser(args['input_file'])
    model = cq.importers.importStep(input_file)
    root = model.val()
    solids = root.Solids()
    print('Imported STEP:', input_file)
    print('Root type:', root.ShapeType())
    print('Solid count:', len(solids))

    for i, solid in enumerate(solids):
        bb = solid.BoundingBox()
        c = solid.Center()
        print('\nSOLID', i)
        print('  valid:', solid.isValid())
        print('  volume:', solid.Volume())
        print('  center:', (c.x, c.y, c.z))
        print('  bbox:', (bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax))
        print('  size:', (bb.xlen, bb.ylen, bb.zlen))
        print('  faces:', len(solid.Faces()), 'edges:', len(solid.Edges()))

        planar = []
        cylindrical = []
        for j, face in enumerate(solid.Faces()):
            try:
                geom = face.geomType()
                fc = face.Center()
                area = face.Area()
                if geom == 'PLANE':
                    planar.append((j, round(fc.z, 5), round(area, 5), round(fc.x, 5), round(fc.y, 5)))
                elif geom == 'CYLINDER':
                    cylindrical.append((j, round(fc.z, 5), round(area, 5), round(fc.x, 5), round(fc.y, 5)))
            except Exception:
                pass
        planar.sort(key=lambda x: (-x[2], x[1]))
        cylindrical.sort(key=lambda x: -x[2])
        print('  largest planar faces (id,z,area,cx,cy):')
        for item in planar[:20]:
            print('   ', item)
        print('  largest cylindrical faces (id,z,area,cx,cy):')
        for item in cylindrical[:20]:
            print('   ', item)

    print('\nInspection iteration: returning original imported geometry unchanged.')
    return model