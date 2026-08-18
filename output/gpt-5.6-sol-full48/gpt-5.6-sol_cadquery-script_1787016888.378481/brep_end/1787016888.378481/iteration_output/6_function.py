def my_cad_function(args):
    import os
    import itertools
    import statistics
    import cadquery as cq
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
    from OCP.ShapeFix import ShapeFix_Shape

    input_file = os.path.expanduser(args['input_file'])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, 'val') else imported
    solids = list(root.Solids())
    print('Imported solids:', len(solids))
    if not solids:
        raise RuntimeError('No solids imported from input STEP file')

    # Locate SEC-01 by its documented bounding-box center.
    def target_score(shape):
        b = shape.BoundingBox()
        c = b.center
        return abs(c.x + 40.0) + abs(c.y + 10.5) + abs(c.z - 12.5)

    target_index = min(range(len(solids)), key=lambda i: target_score(solids[i]))
    target = solids[target_index]
    tb = target.BoundingBox()
    print('Target index:', target_index)
    print('Target bbox:', tb.xmin, tb.xmax, tb.ymin, tb.ymax, tb.zmin, tb.zmax)
    print('Initial target valid:', target.isValid())
    print('Initial target volume:', target.Volume())
    if not target.isValid():
        raise RuntimeError('SEC-01 is invalid before editing')

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
        print(label, 'valid:', shape.isValid(), 'solid count:', count)
        if not shape.isValid() or count != 1:
            raise RuntimeError(label + ' did not produce one valid solid')
        return shape

    def boolean_fuse(base, tool, label):
        before = base.Volume()
        op = BRepAlgoAPI_Fuse(base.wrapped, tool.wrapped)
        op.SetFuzzyValue(1.0e-4)
        op.Build()
        if not op.IsDone() or op.Shape().IsNull():
            raise RuntimeError(label + ' fuse failed')
        result = normalize(cq.Shape.cast(op.Shape()), label)
        print(label, 'volume delta:', result.Volume() - before)
        return result

    def boolean_cut(base, tool, label):
        before = base.Volume()
        op = BRepAlgoAPI_Cut(base.wrapped, tool.wrapped)
        op.SetFuzzyValue(1.0e-4)
        op.Build()
        if not op.IsDone() or op.Shape().IsNull():
            raise RuntimeError(label + ' cut failed')
        result = normalize(cq.Shape.cast(op.Shape()), label)
        removed = before - result.Volume()
        print(label, 'removed volume:', removed)
        if removed <= 1.0e-5:
            raise RuntimeError(label + ' did not intersect the target')
        return result

    # Inspect rear-normal cylindrical faces. The previous function used ymax as
    # the rear face, but SEC-01's mounting datum is on the opposite, ymin side.
    # Pattern detection is retained so the edit remains robust to STEP ordering.
    observations = []
    for face in target.Faces():
        try:
            if face.geomType() != 'CYLINDER':
                continue
            cyl = face._geomAdaptor().Cylinder()
            axis = cyl.Axis()
            direction = axis.Direction()
            if abs(direction.Y()) < 0.97:
                continue
            loc = axis.Location()
            radius = float(cyl.Radius())
            fb = face.BoundingBox()
            if radius < 0.65 or radius > 2.60:
                continue
            if loc.X() < tb.xmin + 2.0 or loc.X() > tb.xmax - 2.0:
                continue
            if loc.Z() < tb.zmin + 1.5 or loc.Z() > tb.zmax - 1.5:
                continue

            dmin = max(0.0, fb.ymax - tb.ymin)
            dmax = max(0.0, tb.ymax - fb.ymin)
            if fb.ymin <= tb.ymin + 0.65:
                observations.append({
                    'side': 'ymin', 'x': float(loc.X()), 'z': float(loc.Z()),
                    'r': radius, 'depth': dmin
                })
            if fb.ymax >= tb.ymax - 0.65:
                observations.append({
                    'side': 'ymax', 'x': float(loc.X()), 'z': float(loc.Z()),
                    'r': radius, 'depth': dmax
                })
        except Exception:
            pass

    for item in observations:
        print('Rear-normal cylinder candidate:', item)

    # Merge stepped/chamfered cylindrical faces belonging to the same opening.
    grouped = {'ymin': [], 'ymax': []}
    for side in ('ymin', 'ymax'):
        side_obs = [o for o in observations if o['side'] == side]
        for obs in side_obs:
            group = None
            for existing in grouped[side]:
                if abs(existing['x'] - obs['x']) < 0.20 and abs(existing['z'] - obs['z']) < 0.20:
                    group = existing
                    break
            if group is None:
                grouped[side].append({
                    'x': obs['x'], 'z': obs['z'], 'radii': [obs['r']],
                    'depths': [obs['depth']]
                })
            else:
                group['radii'].append(obs['r'])
                group['depths'].append(obs['depth'])

    def find_three_point_pattern(points):
        best = None
        best_score = 1.0e9
        if len(points) < 3:
            return None
        for a, b, c in itertools.permutations(points, 3):
            # a and b form the upper row; c is the lower central point.
            if a['x'] >= b['x']:
                continue
            row_error = abs(a['z'] - b['z'])
            upper_z = 0.5 * (a['z'] + b['z'])
            center_x = 0.5 * (a['x'] + b['x'])
            center_error = abs(c['x'] - center_x)
            vertical_pitch = upper_z - c['z']
            horizontal_pitch = b['x'] - a['x']
            if vertical_pitch < 2.0 or horizontal_pitch < 3.0:
                continue
            symmetry_error = abs((center_x - a['x']) - (b['x'] - center_x))
            score = row_error * 8.0 + center_error * 5.0 + symmetry_error
            if score < best_score:
                best_score = score
                best = (a, b, c)
        return best

    pattern = None
    rear_side = None
    for side in ('ymin', 'ymax'):
        candidate = find_three_point_pattern(grouped[side])
        if candidate is not None:
            score = abs(candidate[0]['z'] - candidate[1]['z']) + abs(
                candidate[2]['x'] - 0.5 * (candidate[0]['x'] + candidate[1]['x']))
            if pattern is None or score < pattern[0]:
                pattern = (score, candidate)
                rear_side = side

    if pattern is not None:
        upper_left, upper_right, obsolete = pattern[1]
        left_x = upper_left['x']
        right_x = upper_right['x']
        upper_z = 0.5 * (upper_left['z'] + upper_right['z'])
        lower_z = obsolete['z']
        obsolete_x = obsolete['x']
        all_pattern = [upper_left, upper_right, obsolete]
        pilot_radius = statistics.median([min(p['radii']) for p in all_pattern])
        opening_radius = max(obsolete['radii'])
        hole_depth = statistics.median([max(p['depths']) for p in all_pattern])
        print('Detected original three-point pattern on:', rear_side)
    else:
        # Documented SEC-01 geometry fallback. FACE 145 is at ymin, not ymax.
        rear_side = 'ymin'
        center_x = 0.5 * (tb.xmin + tb.xmax)
        left_x = center_x - 4.5
        right_x = center_x + 4.5
        upper_z = tb.zmin + 15.5
        lower_z = tb.zmin + 5.0
        obsolete_x = center_x
        pilot_radius = 1.20
        opening_radius = 1.65
        hole_depth = 3.0
        print('Pattern-face detection fallback used')

    pilot_radius = max(0.90, min(pilot_radius, 1.55))
    opening_radius = max(pilot_radius + 0.15, min(opening_radius, 2.25))
    hole_depth = max(1.5, min(hole_depth, 5.0))

    print('Rear side:', rear_side)
    print('Existing upper row:', [(left_x, upper_z), (right_x, upper_z)])
    print('Obsolete lower center:', (obsolete_x, lower_z))
    print('New lower row:', [(left_x, lower_z), (right_x, lower_z)])
    print('Pilot radius:', pilot_radius, 'opening radius:', opening_radius, 'depth:', hole_depth)

    if rear_side == 'ymin':
        rear_y = tb.ymin
        inward = cq.Vector(0, 1, 0)
        outside_start = lambda x, z: cq.Vector(x, rear_y - 0.20, z)
        flush_start = lambda x, z: cq.Vector(x, rear_y, z)
    else:
        rear_y = tb.ymax
        inward = cq.Vector(0, -1, 0)
        outside_start = lambda x, z: cq.Vector(x, rear_y + 0.20, z)
        flush_start = lambda x, z: cq.Vector(x, rear_y, z)

    edited = target

    # Fill the complete obsolete lower-center opening from the rear datum to
    # slightly beyond its detected termination. The cylinder remains entirely
    # inside the original exterior envelope.
    plug = cq.Solid.makeCylinder(
        opening_radius + 0.08,
        hole_depth + 0.15,
        flush_start(obsolete_x, lower_z),
        inward
    )
    edited = boolean_fuse(edited, plug, 'close obsolete lower-center mounting hole')

    # Create the missing lower-left and lower-right points, using the same
    # columns as the retained upper pair and the row elevation of the removed
    # central point. This produces the requested rectangular 2-by-2 pattern.
    new_centers = [(left_x, lower_z), (right_x, lower_z)]
    for index, (x, z) in enumerate(new_centers, 1):
        pilot = cq.Solid.makeCylinder(
            pilot_radius,
            hole_depth + 0.40,
            outside_start(x, z),
            inward
        )
        edited = boolean_cut(edited, pilot, 'new lower mounting pilot %d' % index)

        # Match the stepped/finished appearance of the inherited mounting
        # openings with a shallow entry relief.
        relief_radius = min(opening_radius, pilot_radius + 0.40)
        relief_depth = min(0.55, max(0.25, hole_depth * 0.15))
        relief = cq.Solid.makeCylinder(
            relief_radius,
            relief_depth + 0.20,
            outside_start(x, z),
            inward
        )
        try:
            edited = boolean_cut(edited, relief, 'new lower entry relief %d' % index)
        except Exception as exc:
            print('Nonfatal entry-relief warning:', exc)

    edited = normalize(edited, 'final edited SEC-01')
    print('Final target volume:', edited.Volume())

    output_solids = list(solids)
    output_solids[target_index] = edited
    result = cq.Compound.makeCompound(output_solids)
    print('Output solid count:', len(result.Solids()))
    print('Output compound valid:', result.isValid())
    if len(result.Solids()) != len(solids):
        raise RuntimeError('Assembly solid count changed unexpectedly')
    return result
