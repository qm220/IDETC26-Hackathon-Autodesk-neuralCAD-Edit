def my_cad_function(args):
    input_file = os.path.expanduser(args['input_file'])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, 'val') else imported
    solids = list(root.Solids())
    print('Imported solids:', len(solids))

    def bbox_tuple(s):
        b = s.BoundingBox()
        return (b.xmin, b.xmax, b.ymin, b.ymax, b.zmin, b.zmax)

    for i, s in enumerate(solids):
        b = bbox_tuple(s)
        print('SOLID %d bbox x=(%.3f, %.3f) y=(%.3f, %.3f) z=(%.3f, %.3f) volume=%.3f' %
              (i, b[0], b[1], b[2], b[3], b[4], b[5], s.Volume()))

    # Identify the geometry-described target and reference by their STEP locations.
    target_index = min(range(len(solids)), key=lambda i: abs(solids[i].BoundingBox().center.x + 40.0))
    reference_index = min(range(len(solids)), key=lambda i: abs(solids[i].BoundingBox().center.x - 40.0))
    target = solids[target_index]
    reference = solids[reference_index]
    tb = target.BoundingBox()
    rb = reference.BoundingBox()
    print('Target solid index:', target_index, 'Reference solid index:', reference_index)

    def y_cylinder_groups(s):
        groups = {}
        for face in s.Faces():
            try:
                if face.geomType() != 'CYLINDER':
                    continue
                cyl = face._geomAdaptor().Cylinder()
                axis = cyl.Axis()
                direction = axis.Direction()
                if abs(direction.Y()) < 0.95:
                    continue
                location = axis.Location()
                radius = float(cyl.Radius())
                fb = face.BoundingBox()
                key = (round(location.X(), 3), round(location.Z(), 3))
                item = groups.setdefault(key, {'x': location.X(), 'z': location.Z(), 'faces': []})
                item['faces'].append({
                    'radius': radius,
                    'ymin': fb.ymin,
                    'ymax': fb.ymax,
                    'area': face.Area()
                })
            except Exception:
                continue
        return groups

    target_groups_all = y_cylinder_groups(target)
    reference_groups_all = y_cylinder_groups(reference)

    def print_groups(label, groups):
        print(label)
        for key in sorted(groups):
            fs = groups[key]['faces']
            radii = sorted(set(round(f['radius'], 4) for f in fs))
            ymin = min(f['ymin'] for f in fs)
            ymax = max(f['ymax'] for f in fs)
            print('  center x=%.3f z=%.3f radii=%s y=(%.3f, %.3f)' %
                  (groups[key]['x'], groups[key]['z'], radii, ymin, ymax))

    print_groups('Target Y-axis cylindrical groups:', target_groups_all)
    print_groups('Reference Y-axis cylindrical groups:', reference_groups_all)

    def mounting_candidates(groups, bbox):
        result = []
        for g in groups.values():
            radii = [f['radius'] for f in g['faces']]
            rmin = min(radii)
            rmax = max(radii)
            # M2-M4 pilot/clearance mounting geometry; reject principal flow bores.
            if rmin < 0.65 or rmin > 2.25 or rmax > 3.25:
                continue
            if not (bbox.xmin + 1.0 < g['x'] < bbox.xmax - 1.0):
                continue
            if not (bbox.zmin + 1.0 < g['z'] < bbox.zmax - 1.0):
                continue
            result.append(g)
        return result

    target_candidates = mounting_candidates(target_groups_all, tb)
    reference_candidates = mounting_candidates(reference_groups_all, rb)

    def find_rectangle(candidates):
        if len(candidates) < 4:
            return []
        best = None
        n = len(candidates)
        import itertools
        for combo in itertools.combinations(candidates, 4):
            xs = sorted(g['x'] for g in combo)
            zs = sorted(g['z'] for g in combo)
            # In a rectangular pattern the first two and last two coordinates coincide.
            xerr = abs(xs[1] - xs[0]) + abs(xs[3] - xs[2])
            zerr = abs(zs[1] - zs[0]) + abs(zs[3] - zs[2])
            xpitch = 0.5 * (xs[2] + xs[3]) - 0.5 * (xs[0] + xs[1])
            zpitch = 0.5 * (zs[2] + zs[3]) - 0.5 * (zs[0] + zs[1])
            if xpitch < 4.0 or zpitch < 4.0:
                continue
            score = xerr + zerr
            if best is None or score < best[0]:
                best = (score, list(combo))
        if best and best[0] < 1.0:
            return best[1]
        return []

    reference_pattern = find_rectangle(reference_candidates)
    if len(reference_pattern) != 4:
        print('Warning: exact four-hole reference rectangle was not detected; using inferred Aqua pattern.')
        # Conservative fallback based on the reference face envelope.
        ref_xs = [rb.xmin + 5.0, rb.xmax - 5.0]
        ref_zs = [rb.zmin + 6.0, rb.zmax - 6.0]
        reference_pattern = [
            {'x': x, 'z': z, 'faces': [{'radius': 1.25, 'ymin': rb.ymax - 5.0, 'ymax': rb.ymax, 'area': 1.0}]}
            for x in ref_xs for z in ref_zs
        ]

    ref_x_low = sum(sorted(g['x'] for g in reference_pattern)[:2]) / 2.0
    ref_x_high = sum(sorted(g['x'] for g in reference_pattern)[2:]) / 2.0
    ref_z_low = sum(sorted(g['z'] for g in reference_pattern)[:2]) / 2.0
    ref_z_high = sum(sorted(g['z'] for g in reference_pattern)[2:]) / 2.0
    x_left_offset = ref_x_low - rb.xmin
    x_right_offset = rb.xmax - ref_x_high
    z_bottom_offset = ref_z_low - rb.zmin
    z_top_offset = rb.zmax - ref_z_high

    new_xs = [tb.xmin + x_left_offset, tb.xmax - x_right_offset]
    new_zs = [tb.zmin + z_bottom_offset, tb.zmax - z_top_offset]

    # Keep centers in the substantial rear-wall region if the two envelopes differ.
    new_xs[0] = max(new_xs[0], tb.xmin + 3.5)
    new_xs[1] = min(new_xs[1], tb.xmax - 3.5)
    new_zs[0] = max(new_zs[0], tb.zmin + 4.5)
    new_zs[1] = min(new_zs[1], tb.zmax - 3.5)

    all_ref_faces = [f for g in reference_pattern for f in g['faces']]
    pilot_radius = min(f['radius'] for f in all_ref_faces)
    pilot_radius = max(1.0, min(pilot_radius, 2.0))

    # Infer whether the reference holes enter from ymax or ymin, and copy their depth.
    ref_touch_max = sum(1 for f in all_ref_faces if abs(f['ymax'] - rb.ymax) < 0.25)
    ref_touch_min = sum(1 for f in all_ref_faces if abs(f['ymin'] - rb.ymin) < 0.25)
    entry_from_ymax = ref_touch_max >= ref_touch_min
    if entry_from_ymax:
        ref_depths = [rb.ymax - f['ymin'] for f in all_ref_faces if abs(f['ymax'] - rb.ymax) < 0.5]
    else:
        ref_depths = [f['ymax'] - rb.ymin for f in all_ref_faces if abs(f['ymin'] - rb.ymin) < 0.5]
    hole_depth = max(ref_depths) if ref_depths else 5.0
    hole_depth = max(3.0, min(hole_depth, tb.ylen + 0.4))
    print('Reference-derived pilot radius %.3f, depth %.3f, entry_from_ymax=%s' %
          (pilot_radius, hole_depth, entry_from_ymax))
    print('New four-point centers:', [(round(x, 3), round(z, 3)) for x in new_xs for z in new_zs])

    # Locate the obsolete triangular three-point pattern on the target.
    old_pattern = []
    if len(target_candidates) >= 3:
        import itertools
        best = None
        for combo in itertools.combinations(target_candidates, 3):
            xs = sorted(g['x'] for g in combo)
            zs = sorted(g['z'] for g in combo)
            # Two points form one row; the third is near their horizontal midpoint.
            for a, b, c in ((combo[0], combo[1], combo[2]), (combo[0], combo[2], combo[1]), (combo[1], combo[2], combo[0])):
                row_error = abs(a['z'] - b['z'])
                mid_error = abs(c['x'] - 0.5 * (a['x'] + b['x']))
                separation = abs(c['z'] - 0.5 * (a['z'] + b['z']))
                if abs(a['x'] - b['x']) < 4.0 or separation < 3.0:
                    continue
                score = row_error + mid_error
                if best is None or score < best[0]:
                    best = (score, [a, b, c])
        if best and best[0] < 2.0:
            old_pattern = best[1]

    edited = target
    if len(old_pattern) == 3:
        print('Removing old three-point centers:', [(round(g['x'], 3), round(g['z'], 3)) for g in old_pattern])
        for g in old_pattern:
            max_r = max(f['radius'] for f in g['faces']) + 0.35
            gymin = min(f['ymin'] for f in g['faces'])
            gymax = max(f['ymax'] for f in g['faces'])
            # Fill only the original rear-hole axial extent, with small healing overlap.
            start_y = gymin - 0.15
            length = gymax - gymin + 0.30
            plug = cq.Solid.makeCylinder(max_r, length,
                                         cq.Vector(g['x'], start_y, g['z']),
                                         cq.Vector(0, 1, 0))
            edited = edited.fuse(plug)
    else:
        print('Warning: obsolete triangular pattern not uniquely detected; no unrelated openings were filled.')

    # Cut the new symmetric 2 x 2 mounting pattern normal to the rear datum.
    for x in new_xs:
        for z in new_zs:
            if entry_from_ymax:
                origin_y = tb.ymax + 0.2
                direction = cq.Vector(0, -1, 0)
            else:
                origin_y = tb.ymin - 0.2
                direction = cq.Vector(0, 1, 0)
            cutter = cq.Solid.makeCylinder(pilot_radius, hole_depth + 0.4,
                                            cq.Vector(x, origin_y, z), direction)
            edited = edited.cut(cutter)
            # Small standardized lead-in matching a tapped-hole entrance treatment.
            chamfer_depth = min(0.4, pilot_radius * 0.3)
            chamfer_outer = pilot_radius + min(0.35, pilot_radius * 0.25)
            cone = cq.Solid.makeCone(chamfer_outer, pilot_radius, chamfer_depth,
                                     cq.Vector(x, origin_y, z), direction)
            edited = edited.cut(cone)

    print('Edited target valid:', edited.isValid(), 'volume:', edited.Volume())
    output_solids = list(solids)
    output_solids[target_index] = edited
    result = cq.Compound.makeCompound(output_solids)
    print('Output solids:', len(result.Solids()), 'valid:', result.isValid())
    return result