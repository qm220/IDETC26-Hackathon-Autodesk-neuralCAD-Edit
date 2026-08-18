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
        raise RuntimeError('No solids were imported from the input STEP file')

    # Locate SEC-01 from its documented assembly position.
    def target_score(shape):
        b = shape.BoundingBox()
        c = b.center
        return abs(c.x + 40.0) + abs(c.y + 10.5) + abs(c.z - 12.5)

    target_index = min(range(len(solids)), key=lambda i: target_score(solids[i]))
    target = solids[target_index]
    tb = target.BoundingBox()
    rear_y = tb.ymax
    cx = 0.5 * (tb.xmin + tb.xmax)

    print('Target solid index:', target_index)
    print('Target bbox:', tb.xmin, tb.xmax, tb.ymin, tb.ymax, tb.zmin, tb.zmax)
    print('Target valid:', target.isValid())
    print('Target volume:', target.Volume())

    # Existing rear pattern: two upper points and one obsolete lower-central point.
    # Resulting pattern: two columns by two rows. The lower centers retain the
    # available spacing established in the previous geometric inspection.
    upper_z = tb.zmin + 15.5
    lower_z = tb.zmin + 5.5
    column_offset = 4.5
    upper_centers = [(cx - column_offset, upper_z),
                     (cx + column_offset, upper_z)]
    lower_centers = [(cx - column_offset, lower_z),
                     (cx + column_offset, lower_z)]
    obsolete_center = (cx, tb.zmin + 5.0)

    print('Preserved upper centers:', upper_centers)
    print('New lower centers:', lower_centers)
    print('Obsolete center:', obsolete_center)

    def fix_shape(shape):
        try:
            fixer = ShapeFix_Shape(shape.wrapped)
            fixer.Perform()
            fixed = cq.Shape.cast(fixer.Shape())
            if fixed is not None and fixed.isValid():
                return fixed
        except Exception as exc:
            print('Shape-fix warning:', exc)
        return shape

    def boolean_cut(base, tool, label):
        before = base.Volume()
        op = BRepAlgoAPI_Cut(base.wrapped, tool.wrapped)
        op.SetFuzzyValue(2.0e-5)
        op.SetNonDestructive(True)
        op.Build()
        if not op.IsDone() or op.Shape().IsNull():
            raise RuntimeError('Boolean cut failed: ' + label)
        result = cq.Shape.cast(op.Shape())
        if result is None:
            raise RuntimeError('Boolean cut returned no shape: ' + label)
        if not result.isValid():
            result = fix_shape(result)
        if not result.isValid() or len(result.Solids()) != 1:
            raise RuntimeError('Boolean cut produced an invalid result: ' + label)
        removed = before - result.Volume()
        print(label, 'removed volume:', removed)
        if removed <= 1.0e-5:
            raise RuntimeError('Boolean cut removed no material: ' + label)
        return result

    def boolean_fuse(base, tool, label):
        op = BRepAlgoAPI_Fuse(base.wrapped, tool.wrapped)
        op.SetFuzzyValue(2.0e-5)
        op.SetNonDestructive(True)
        op.Build()
        if not op.IsDone() or op.Shape().IsNull():
            raise RuntimeError('Boolean fuse failed: ' + label)
        result = cq.Shape.cast(op.Shape())
        if result is None:
            raise RuntimeError('Boolean fuse returned no shape: ' + label)
        if not result.isValid():
            result = fix_shape(result)
        if not result.isValid() or len(result.Solids()) != 1:
            raise RuntimeError('Boolean fuse produced an invalid result: ' + label)
        print(label, 'added volume:', result.Volume() - base.Volume())
        return result

    edited = target

    # Cut the new holes before filling the old one. This avoids propagating the
    # locally healed topology from the plug into subsequent subtraction booleans.
    pilot_radius = 1.265
    entry_radius = 1.55
    entry_depth = 0.45

    for index, (x, z) in enumerate(lower_centers, 1):
        successful = False
        last_error = None

        # Prefer a useful blind depth, but automatically shorten it if an internal
        # passage or marginal STEP topology makes the deeper boolean invalid.
        for pilot_depth in (3.0, 2.25, 1.60):
            try:
                pilot = cq.Solid.makeCylinder(
                    pilot_radius,
                    pilot_depth + 0.08,
                    cq.Vector(x, rear_y + 0.04, z),
                    cq.Vector(0, -1, 0)
                )
                entry = cq.Solid.makeCylinder(
                    entry_radius,
                    entry_depth + 0.08,
                    cq.Vector(x, rear_y + 0.04, z),
                    cq.Vector(0, -1, 0)
                )
                tool = pilot.fuse(entry)
                if not tool.isValid():
                    tool = fix_shape(tool)
                candidate = boolean_cut(
                    edited, tool,
                    'lower mounting hole %d depth %.2f' % (index, pilot_depth)
                )
                edited = candidate
                print('Accepted pilot depth for lower hole', index, ':', pilot_depth)
                successful = True
                break
            except Exception as exc:
                last_error = exc
                print('Retrying lower hole', index, 'after:', exc)

        if not successful:
            raise RuntimeError('Unable to create lower mounting hole %d: %s' %
                               (index, last_error))

    # Close the obsolete lower-central rear opening after the new holes exist.
    # The shallow overlapping plug restores the rear datum while remaining clear
    # of the deeper longitudinal and transverse manifold passages.
    plug_radius = 1.90
    plug_depth = 1.70
    plug = cq.Solid.makeCylinder(
        plug_radius,
        plug_depth + 0.03,
        cq.Vector(obsolete_center[0], rear_y + 0.03, obsolete_center[1]),
        cq.Vector(0, -1, 0)
    )
    edited = boolean_fuse(edited, plug, 'obsolete lower-center hole closure')

    try:
        cleaned = edited.clean()
        if cleaned is not None and cleaned.isValid() and len(cleaned.Solids()) == 1:
            edited = cleaned
    except Exception as exc:
        print('Nonfatal cleanup warning:', exc)

    print('Edited target valid:', edited.isValid())
    print('Edited target solid count:', len(edited.Solids()))
    print('Edited target volume:', edited.Volume())

    if not edited.isValid() or len(edited.Solids()) != 1:
        raise RuntimeError('Edited SEC-01 is not one valid watertight solid')

    # Verify that both new pilot cylinders exist and that the obsolete cylindrical
    # opening no longer reaches the maximum-Y rear datum.
    detected_lower = set()
    obsolete_open_at_rear = False
    for face in edited.Faces():
        try:
            if face.geomType() != 'CYLINDER':
                continue
            cylinder = face._geomAdaptor().Cylinder()
            axis = cylinder.Axis()
            direction = axis.Direction()
            if abs(direction.Y()) < 0.95:
                continue
            location = axis.Location()
            radius = float(cylinder.Radius())
            fb = face.BoundingBox()

            for x, z in lower_centers:
                if (abs(location.X() - x) < 0.10 and
                        abs(location.Z() - z) < 0.10 and
                        abs(radius - pilot_radius) < 0.10):
                    detected_lower.add((round(x, 3), round(z, 3)))

            if (abs(location.X() - obsolete_center[0]) < 0.10 and
                    abs(location.Z() - obsolete_center[1]) < 0.10 and
                    fb.ymax >= rear_y - 0.04 and
                    radius < plug_radius + 0.15):
                obsolete_open_at_rear = True
        except Exception:
            pass

    print('Detected lower mounting centers:', sorted(detected_lower))
    print('Detected lower mounting count:', len(detected_lower))
    print('Obsolete opening reaches rear datum:', obsolete_open_at_rear)

    if len(detected_lower) != 2:
        raise RuntimeError('Both new lower mounting holes could not be verified')
    if obsolete_open_at_rear:
        raise RuntimeError('The obsolete lower-central mounting opening remains visible')

    output_solids = list(solids)
    output_solids[target_index] = edited
    result = cq.Compound.makeCompound(output_solids)

    print('Output solids:', len(result.Solids()))
    print('Output valid:', result.isValid())

    if len(result.Solids()) != len(solids):
        raise RuntimeError('Assembly solid count changed unexpectedly')

    return result