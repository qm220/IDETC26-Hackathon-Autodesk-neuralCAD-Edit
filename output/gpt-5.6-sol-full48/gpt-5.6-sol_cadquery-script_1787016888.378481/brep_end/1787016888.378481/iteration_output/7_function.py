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
        raise RuntimeError('No solids found in the input STEP file')

    # Locate SEC-01 from its documented bounding-box center.
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
        print(label, 'valid:', shape.isValid(), 'solids:', len(shape.Solids()), 'volume:', shape.Volume())
        if not shape.isValid() or len(shape.Solids()) != 1:
            raise RuntimeError(label + ' failed to produce one valid solid')
        return shape

    def fuse(base, tool, label):
        before = base.Volume()
        operation = BRepAlgoAPI_Fuse(base.wrapped, tool.wrapped)
        operation.SetFuzzyValue(1.0e-4)
        operation.Build()
        if not operation.IsDone() or operation.Shape().IsNull():
            raise RuntimeError(label + ' fuse failed')
        result = normalize(cq.Shape.cast(operation.Shape()), label)
        print(label, 'added volume:', result.Volume() - before)
        return result

    def cut(base, tool, label):
        before = base.Volume()
        operation = BRepAlgoAPI_Cut(base.wrapped, tool.wrapped)
        operation.SetFuzzyValue(1.0e-4)
        operation.Build()
        if not operation.IsDone() or operation.Shape().IsNull():
            raise RuntimeError(label + ' cut failed')
        result = normalize(cq.Shape.cast(operation.Shape()), label)
        removed = before - result.Volume()
        print(label, 'removed volume:', removed)
        if removed < 1.0e-4:
            raise RuntimeError(label + ' did not intersect solid material')
        return result

    # The latest rendering shows that the visible three-point rear pattern is
    # on the ymin datum. The previous implementation incorrectly selected
    # ymax cylindrical features and therefore left the triangular pattern
    # unchanged. Use the geometry-confirmed ymin mounting datum here.
    rear_y = bb.ymin
    inward = cq.Vector(0, 1, 0)

    center_x = 0.5 * (bb.xmin + bb.xmax)       # -40.0
    left_x = center_x - 4.5                    # -44.5
    right_x = center_x + 4.5                   # -35.5
    upper_z = bb.zmin + 15.5                   # retained upper row
    lower_z = bb.zmin + 5.0                    # old central-hole row

    print('Rear mounting datum: ymin =', rear_y)
    print('Retained upper row:', [(left_x, upper_z), (right_x, upper_z)])
    print('Obsolete lower center:', (center_x, lower_z))
    print('New lower row:', [(left_x, lower_z), (right_x, lower_z)])

    edited = target

    # Heal the old lower-central mounting opening. Its cylindrical face was
    # measured in the source STEP at radius 2.5 mm and approximately 4 mm
    # depth. The slight radial/depth overlap ensures a complete watertight fill.
    plug_radius = 2.58
    plug_depth = 4.20
    plug = cq.Solid.makeCylinder(
        plug_radius,
        plug_depth,
        cq.Vector(center_x, rear_y, lower_z),
        inward
    )
    edited = fuse(edited, plug, 'close obsolete lower-center rear hole')

    # Add two equivalent blind stepped mounting holes at the lower corners.
    # These share the columns of the retained upper pair and create a true
    # rectangular two-column by two-row mounting pattern.
    pilot_radius = 1.2645
    pilot_depth = 4.00
    entry_radius = 1.543
    entry_depth = 0.72
    outside_offset = 0.15

    for number, x in enumerate((left_x, right_x), 1):
        start = cq.Vector(x, rear_y - outside_offset, lower_z)

        pilot = cq.Solid.makeCylinder(
            pilot_radius,
            pilot_depth + outside_offset,
            start,
            inward
        )
        edited = cut(edited, pilot, 'lower rear pilot hole %d' % number)

        entry_relief = cq.Solid.makeCylinder(
            entry_radius,
            entry_depth + outside_offset,
            start,
            inward
        )
        edited = cut(edited, entry_relief, 'lower rear entry relief %d' % number)

    edited = normalize(edited, 'final edited SEC-01')

    # Preserve every other assembly component without modification.
    output_solids = list(solids)
    output_solids[target_index] = edited
    result = cq.Compound.makeCompound(output_solids)

    print('Final assembly solid count:', len(result.Solids()))
    print('Final assembly valid:', result.isValid())
    print('Final target volume:', edited.Volume())

    if len(result.Solids()) != len(solids):
        raise RuntimeError('Assembly solid count changed unexpectedly')
    if not result.isValid():
        raise RuntimeError('Output assembly compound is invalid')

    return result