def my_cad_function(args):
    import os
    input_file = os.path.expanduser(args['input_file'])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    print('=== MODEL INSPECTION ===')
    print(f'Valid: {shape.isValid()}')
    bb = shape.BoundingBox()
    print(f'Overall bbox: x=({bb.xmin:.3f},{bb.xmax:.3f}) y=({bb.ymin:.3f},{bb.ymax:.3f}) z=({bb.zmin:.3f},{bb.zmax:.3f})')
    print(f'Overall size: {bb.xlen:.3f} x {bb.ylen:.3f} x {bb.zlen:.3f} mm')

    solids = shape.Solids()
    print(f'Solid count: {len(solids)}')
    for i, solid in enumerate(solids):
        sb = solid.BoundingBox()
        c = solid.Center()
        print(
            f'SOLID {i:02d}: volume={solid.Volume():.3f}, '
            f'center=({c.x:.3f},{c.y:.3f},{c.z:.3f}), '
            f'bbox=({sb.xmin:.3f},{sb.xmax:.3f}) '
            f'({sb.ymin:.3f},{sb.ymax:.3f}) '
            f'({sb.zmin:.3f},{sb.zmax:.3f}), '
            f'size=({sb.xlen:.3f},{sb.ylen:.3f},{sb.zlen:.3f}), '
            f'faces={len(solid.Faces())}'
        )
        cylinders = []
        for j, face in enumerate(solid.Faces()):
            try:
                if face.geomType() == 'CYLINDER':
                    fb = face.BoundingBox()
                    fc = face.Center()
                    cylinders.append(
                        f'f{j}: center=({fc.x:.2f},{fc.y:.2f},{fc.z:.2f}) '
                        f'bboxSize=({fb.xlen:.2f},{fb.ylen:.2f},{fb.zlen:.2f}) '
                        f'area={face.Area():.2f}'
                    )
            except Exception:
                pass
        if cylinders:
            print('  Cylindrical faces:')
            for item in cylinders:
                print('   ', item)

    return model