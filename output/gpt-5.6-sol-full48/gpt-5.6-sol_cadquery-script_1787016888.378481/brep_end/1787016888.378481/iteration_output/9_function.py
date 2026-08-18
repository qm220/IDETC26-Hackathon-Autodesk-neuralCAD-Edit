def my_cad_function(args):
    import os
    import cadquery as cq
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
    from OCP.ShapeFix import ShapeFix_Shape

    input_file = os.path.expanduser(args['input_file'])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, 'val') else imported
    solids = list(root.Solids())
    print('Imported solids:', len(solids))
    if not solids:
        raise RuntimeError('No solids found in input STEP')

    def target_score(shape):
        bb = shape.BoundingBox()
        c = bb.center
        return abs(c.x + 40.0) + abs(c.y + 10.5) + abs(c.z - 12.5)

    target_index = min(range(len(solids)), key=lambda i: target_score(solids[i]))
    target = solids[target_index]
    bb = target.BoundingBox()
    print('Target index:', target_index)
    print('Target bbox:', bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax)
    print('Initial target volume:', target.Volume())
    print('Initial target valid:', target.isValid())

    if not target.isValid():
        raise RuntimeError('Target SEC-01 is invalid before editing')

    def repair(shape):
        try:
            if shape.isValid():
                return shape
        except Exception:
            pass
        fixer = ShapeFix_Shape(shape.wrapped)
        fixer.Perform()
        return cq.Shape.cast(fixer.Shape())

    def normalize(shape, label):
        shape = repair(shape)
        try:
            cleaned = shape.clean()
            if cleaned is not None:
                shape = cleaned
        except Exception as exc:
            print(label, 'clean warning:', exc)
        shape = repair(shape)
        count = len(shape.Solids())
        print(label, 'valid:', shape.isValid(), 'solids:', count, 'volume:', shape.Volume())
        if not shape.isValid() or count != 1:
            raise RuntimeError(label + ' did not produce one valid solid')
        return shape

    def fuse(base, tool, label):
        before = base.Volume()
        op = BRepAlgoAPI_Fuse(base.wrapped, tool.wrapped)
        op.SetFuzzyValue(1.0e-4)
        op.Build()
        if not op.IsDone() or op.Shape().IsNull():
            raise RuntimeError(label + ' fuse failed')
        result = normalize(cq.Shape.cast(op.Shape()), label)
        print(label, 'added volume:', result.Volume() - before)
        return result

    def cut(base, tool, label):
        before = base.Volume()
        op = BRepAlgoAPI_Cut(base.wrapped, tool.wrapped)
        op.SetFuzzyValue(1.0e-4)
        op.Build()
        if not op.IsDone() or op.Shape().IsNull():
            raise RuntimeError(label + ' cut failed')
        result = normalize(cq.Shape.cast(op.Shape()), label)
        removed = before - result.Volume()
        print(label, 'removed volume:', removed)
        if removed < 1.0e-4:
            raise RuntimeError(label + ' did not intersect material')
        return result

    # Existing three-point pattern on the upper mounting datum consists of
    # two points in the y=-15.5 row and one central point in the y=-5 row.
    # Retain the pair, close the central point, and cut a symmetric pair at
    # the same row to create a rectangular four-point mounting pattern.
    top_z = bb.zmax
    center_x = 0.5 * (bb.xmin + bb.xmax)
    left_x = center_x - 4.5
    right_x = center_x + 4.5
    retained_row_y = bb.ymin + 5.5
    new_row_y = bb.ymax - 5.0

    print('Mounting datum zmax:', top_z)
    print('Retained row:', [(left_x, retained_row_y), (right_x, retained_row_y)])
    print('Obsolete center:', (center_x, new_row_y))
    print('New row:', [(left_x, new_row_y), (right_x, new_row_y)])

    edited = target

    # Fill the obsolete central blind mounting feature. The prior iteration
    # accidentally interchanged Y and Z when positioning this cylinder,
    # producing a detached second solid. This plug is correctly positioned
    # on the mounting datum and overlaps the hole walls and blind-hole floor.
    plug_radius = 1.75
    plug_depth = 4.50
    plug_overlap = 0.20
    plug = cq.Solid.makeCylinder(
        plug_radius,
        plug_depth + plug_overlap,
        cq.Vector(center_x, new_row_y, top_z - plug_depth - plug_overlap),
        cq.Vector(0, 0, 1)
    )
    edited = fuse(edited, plug, 'close obsolete central mounting hole')

    # Reproduce the stepped blind geometry of the retained mounting points.
    pilot_radius = 1.2645
    pilot_depth = 4.00
    entry_radius = 1.543
    entry_depth = 0.72
    outside_offset = 0.15

    for number, x in enumerate((left_x, right_x), 1):
        start = cq.Vector(x, new_row_y, top_z + outside_offset)
        pilot = cq.Solid.makeCylinder(
            pilot_radius,
            pilot_depth + outside_offset,
            start,
            cq.Vector(0, 0, -1)
        )
        edited = cut(edited, pilot, 'new mounting pilot hole %d' % number)

        relief = cq.Solid.makeCylinder(
            entry_radius,
            entry_depth + outside_offset,
            start,
            cq.Vector(0, 0, -1)
        )
        edited = cut(edited, relief, 'new mounting entry relief %d' % number)

    edited = normalize(edited, 'final edited SEC-01')

    output_solids = list(solids)
    output_solids[target_index] = edited
    result = cq.Compound.makeCompound(output_solids)

    print('Final assembly solid count:', len(result.Solids()))
    print('Final assembly valid:', result.isValid())
    print('Final target volume:', edited.Volume())

    if len(result.Solids()) != len(solids):
        raise RuntimeError('Assembly solid count changed unexpectedly')
    if not result.isValid():
        raise RuntimeError('Output assembly is invalid')

    return result
