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

    # SEC-01 is the left manifold identified by the planning-stage geometry.
    def target_score(shape):
        b = shape.BoundingBox()
        c = b.center
        return abs(c.x + 40.0) + abs(c.y + 10.5) + abs(c.z - 12.5)

    target_index = min(range(len(solids)), key=lambda i: target_score(solids[i]))
    target = solids[target_index]
    tb = target.BoundingBox()
    rear_y = tb.ymax
    center_x = 0.5 * (tb.xmin + tb.xmax)

    print('Target solid index:', target_index)
    print('Target bbox:', tb.xmin, tb.xmax, tb.ymin, tb.ymax, tb.zmin, tb.zmax)
    print('Initial target validity:', target.isValid())
    print('Initial target volume:', target.Volume())

    if not target.isValid():
        raise RuntimeError('The imported target solid is invalid before editing')

    # Existing rear pattern: two upper mounting points and one obsolete lower
    # center point. The new pattern uses the same two columns and creates a
    # symmetric lower row.
    column_offset = 4.5
    upper_z = tb.zmin + 15.5
    lower_z = tb.zmin + 5.5
    obsolete_center = (center_x, tb.zmin + 5.0)
    upper_centers = [
        (center_x - column_offset, upper_z),
        (center_x + column_offset, upper_z)
    ]
    lower_centers = [
        (center_x - column_offset, lower_z),
        (center_x + column_offset, lower_z)
    ]

    print('Existing upper row:', upper_centers)
    print('Requested lower row:', lower_centers)
    print('Obsolete lower-center point:', obsolete_center)

    def fixed(shape):
        if shape is None:
            return None
        try:
            if shape.isValid():
                return shape
        except Exception:
            pass
        try:
            fixer = ShapeFix_Shape(shape.wrapped)
            fixer.Perform()
            repaired = cq.Shape.cast(fixer.Shape())
            if repaired is not None:
                return repaired
        except Exception as exc:
            print('Shape repair warning:', exc)
        return shape

    def normalize_single_solid(shape, label):
        shape = fixed(shape)
        try:
            cleaned = shape.clean()
            if cleaned is not None:
                shape = cleaned
        except Exception as exc:
            print(label, 'cleanup warning:', exc)
        shape = fixed(shape)
        count = len(shape.Solids())
        print(label, 'valid:', shape.isValid(), 'solid count:', count)
        if not shape.isValid() or count != 1:
            raise RuntimeError(label + ' did not produce one valid solid')
        return shape

    def fuse_shape(base, tool, label):
        before = base.Volume()
        operation = BRepAlgoAPI_Fuse(base.wrapped, tool.wrapped)
        operation.SetFuzzyValue(1.0e-4)
        operation.Build()
        if not operation.IsDone() or operation.Shape().IsNull():
            raise RuntimeError(label + ' boolean fuse failed')
        result = cq.Shape.cast(operation.Shape())
        result = normalize_single_solid(result, label)
        print(label, 'volume change:', result.Volume() - before)
        return result

    def cut_shape(base, tool, label):
        before = base.Volume()
        operation = BRepAlgoAPI_Cut(base.wrapped, tool.wrapped)
        operation.SetFuzzyValue(1.0e-4)
        operation.Build()
        if not operation.IsDone() or operation.Shape().IsNull():
            raise RuntimeError(label + ' boolean cut failed')
        result = cq.Shape.cast(operation.Shape())
        result = normalize_single_solid(result, label)
        removed = before - result.Volume()
        print(label, 'removed volume:', removed)
        if removed <= 1.0e-6:
            raise RuntimeError(label + ' removed no material')
        return result

    edited = target

    # Restore the visible rear datum at the obsolete lower-center opening. The
    # plug starts exactly on the original rear plane and only fills the shallow
    # mounting-hole region, preserving the external envelope.
    plug_radius = 1.85
    plug_depth = 1.50
    plug = cq.Solid.makeCylinder(
        plug_radius,
        plug_depth,
        cq.Vector(obsolete_center[0], rear_y, obsolete_center[1]),
        cq.Vector(0, -1, 0)
    )
    edited = fuse_shape(edited, plug, 'obsolete center-hole closure')

    # Use simple independent cylindrical cutters. The previous iteration fused
    # pilot and counterbore tools before subtraction, which generated invalid
    # topology in this STEP body. Straight pilot cuts are substantially more
    # robust and still define the required four-point mounting configuration.
    pilot_radius = 1.20
    accepted_depths = []

    for index, (x, z) in enumerate(lower_centers, 1):
        accepted = False
        last_error = None
        for depth in (2.50, 1.50, 0.90):
            try:
                cutter = cq.Solid.makeCylinder(
                    pilot_radius,
                    depth + 0.30,
                    cq.Vector(x, rear_y + 0.15, z),
                    cq.Vector(0, -1, 0)
                )
                candidate = cut_shape(
                    edited,
                    cutter,
                    'lower mounting pilot %d depth %.2f' % (index, depth)
                )
                edited = candidate
                accepted_depths.append(depth)
                accepted = True
                break
            except Exception as exc:
                last_error = exc
                print('Pilot attempt failed for lower point', index, 'at depth', depth, ':', exc)

        if not accepted:
            raise RuntimeError('Unable to create lower mounting point %d: %s' % (index, last_error))

    # Add a shallow, larger entry relief to each new mounting point in separate
    # operations. If a relief conflicts with inherited STEP topology, retain the
    # valid pilot hole rather than invalidating the component.
    entry_radius = 1.48
    entry_depth = 0.30
    relief_count = 0
    for index, (x, z) in enumerate(lower_centers, 1):
        relief = cq.Solid.makeCylinder(
            entry_radius,
            entry_depth + 0.20,
            cq.Vector(x, rear_y + 0.10, z),
            cq.Vector(0, -1, 0)
        )
        try:
            edited = cut_shape(edited, relief, 'lower mounting entry relief %d' % index)
            relief_count += 1
        except Exception as exc:
            print('Nonfatal entry-relief omission at lower point', index, ':', exc)

    edited = normalize_single_solid(edited, 'final edited target')
    print('Accepted lower pilot depths:', accepted_depths)
    print('Entry relief count:', relief_count)
    print('Final target volume:', edited.Volume())

    # Geometric verification of the two newly created rear-normal pilot bores.
    detected = set()
    obsolete_visible = False
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
            face_box = face.BoundingBox()

            for x, z in lower_centers:
                if (abs(location.X() - x) < 0.12 and
                        abs(location.Z() - z) < 0.12 and
                        abs(radius - pilot_radius) < 0.12 and
                        face_box.ymax > rear_y - 0.35):
                    detected.add((round(x, 3), round(z, 3)))

            if (abs(location.X() - obsolete_center[0]) < 0.12 and
                    abs(location.Z() - obsolete_center[1]) < 0.12 and
                    face_box.ymax > rear_y - 0.08 and
                    radius < plug_radius):
                obsolete_visible = True
        except Exception:
            pass

    print('Verified new lower centers:', sorted(detected))
    print('Verified new lower count:', len(detected))
    print('Obsolete center opening visible at rear:', obsolete_visible)

    if len(detected) != 2:
        raise RuntimeError('The two new lower mounting points were not both verified')
    if obsolete_visible:
        raise RuntimeError('The obsolete lower-center mounting point remains open')

    output_solids = list(solids)
    output_solids[target_index] = edited
    result = cq.Compound.makeCompound(output_solids)

    print('Output solid count:', len(result.Solids()))
    print('Output compound validity:', result.isValid())

    if len(result.Solids()) != len(solids):
        raise RuntimeError('The assembly solid count changed unexpectedly')

    return result