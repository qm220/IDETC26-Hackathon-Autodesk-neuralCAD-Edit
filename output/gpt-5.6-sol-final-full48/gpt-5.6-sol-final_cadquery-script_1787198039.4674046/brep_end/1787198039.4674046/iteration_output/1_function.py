def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported
    solids = list(root.Solids())
    if not solids:
        raise ValueError("The input STEP file contains no solids")

    # Solid 0 is expected to contain the plastic housing and stationary fan
    # guards. Select it geometrically to remain robust to STEP ordering.
    target_index = max(range(len(solids)), key=lambda i: len(solids[i].Faces()))
    target = solids[target_index]
    target_bb = target.BoundingBox()
    original_valid = target.isValid()
    original_volume = target.Volume()

    # Find long planar faces on the upper and lower exterior rails. In this
    # model Y is vertical, Z follows the long radiator direction, and X is the
    # assembly thickness.
    candidates = []
    planar_y_tolerance = max(1.0e-4, target_bb.ylen * 1.0e-5)
    for face in target.Faces():
        try:
            if face.geomType() != "PLANE":
                continue
            bb = face.BoundingBox()
            if (bb.ylen <= planar_y_tolerance and
                    bb.zlen >= 0.35 * target_bb.zlen and
                    bb.xlen >= 0.08 * target_bb.xlen):
                candidates.append((face, bb))
        except Exception:
            pass

    if len(candidates) < 2:
        raise ValueError("Could not identify the exterior top and bottom rail faces")

    top_face, top_bb = max(candidates, key=lambda item: (item[1].ymax, item[0].Area()))
    bottom_face, bottom_bb = min(candidates, key=lambda item: (item[1].ymin, -item[0].Area()))

    top_y = 0.5 * (top_bb.ymin + top_bb.ymax)
    bottom_y = 0.5 * (bottom_bb.ymin + bottom_bb.ymax)

    z_min = max(top_bb.zmin, bottom_bb.zmin)
    z_max = min(top_bb.zmax, bottom_bb.zmax)
    if z_max <= z_min:
        z_min = min(top_bb.zmin, bottom_bb.zmin)
        z_max = max(top_bb.zmax, bottom_bb.zmax)
    z_span = z_max - z_min
    if z_span <= 10.0:
        raise ValueError("The identified rail surfaces are too short for a slot pattern")

    common_x_min = max(top_bb.xmin, bottom_bb.xmin)
    common_x_max = min(top_bb.xmax, bottom_bb.xmax)
    if common_x_max <= common_x_min:
        common_x_min = max(top_bb.xmin, bottom_bb.xmin)
        common_x_max = min(top_bb.xmax, bottom_bb.xmax)
    common_x_span = common_x_max - common_x_min
    if common_x_span <= 2.0:
        raise ValueError("The identified rail surfaces are too narrow for slots")

    top_x = 0.5 * (top_bb.xmin + top_bb.xmax)
    bottom_x = 0.5 * (bottom_bb.xmin + bottom_bb.xmax)

    # Conservative shallow capsule grooves avoid opening a coolant-containing
    # tank and stay well clear of the rounded perimeter edges.
    slot_width = max(2.0, min(6.0, 0.009 * z_span, 0.18 * common_x_span))
    slot_length = max(2.2 * slot_width, min(0.56 * common_x_span,
                                           common_x_span - 2.2 * slot_width))
    nominal_depth = max(0.35, min(0.80, 0.010 * target_bb.ylen))
    overlap = 0.12

    z_center = 0.5 * (z_min + z_max)
    end_margin = max(2.5 * slot_width, 0.065 * z_span)
    pattern_min = z_min + end_margin
    pattern_max = z_max - end_margin

    # Use a moderate number of slots so each Boolean remains local and robust.
    desired_count = 13
    if pattern_max <= pattern_min:
        raise ValueError("Insufficient usable rail length after edge clearances")
    pitch = (pattern_max - pattern_min) / float(desired_count - 1)
    base_positions = [pattern_min + i * pitch for i in range(desired_count)]

    # Establish keep-outs by projecting separate fittings and mounting pieces
    # onto each exterior rail. The top also receives an explicit central cap
    # clearance because the service cap lies between the two fans.
    clearance = max(1.5 * slot_width, 0.012 * z_span)
    proximity = max(12.0, 0.045 * z_span)
    top_keepouts = [(z_center - max(2.8 * slot_width, 0.038 * z_span),
                     z_center + max(2.8 * slot_width, 0.038 * z_span))]
    bottom_keepouts = []

    for i, solid in enumerate(solids):
        if i == target_index:
            continue
        try:
            bb = solid.BoundingBox()
            if (bb.xmax >= top_bb.xmin and bb.xmin <= top_bb.xmax and
                    bb.ymax > top_y + 0.1 and bb.ymin < top_y + proximity):
                top_keepouts.append((bb.zmin - clearance, bb.zmax + clearance))
            if (bb.xmax >= bottom_bb.xmin and bb.xmin <= bottom_bb.xmax and
                    bb.ymin < bottom_y - 0.1 and bb.ymax > bottom_y - proximity):
                bottom_keepouts.append((bb.zmin - clearance, bb.zmax + clearance))
        except Exception:
            pass

    def filter_positions(keepouts):
        half = 0.5 * slot_width
        return [z for z in base_positions
                if not any(z + half > lo and z - half < hi for lo, hi in keepouts)]

    top_positions = filter_positions(top_keepouts)
    bottom_positions = filter_positions(bottom_keepouts)

    # Avoid losing an entire pattern due to a coarse freeform fitting bbox.
    if len(top_positions) < 5:
        central = top_keepouts[0]
        top_positions = filter_positions([central])
    if len(bottom_positions) < 5:
        bottom_positions = list(base_positions)

    def capsule_cutter(x, surface_y, z, inward_normal, depth):
        if inward_normal < 0:
            origin = (x, surface_y + overlap, z)
            normal = (0, -1, 0)
        else:
            origin = (x, surface_y - overlap, z)
            normal = (0, 1, 0)
        plane = cq.Plane(origin=origin, xDir=(1, 0, 0), normal=normal)
        return (cq.Workplane(plane)
                .slot2D(slot_length, slot_width, 0)
                .extrude(depth + overlap)
                .val())

    # Apply cutters one at a time. A many-tool compound Boolean caused an
    # invalid B-rep previously; local sequential cuts are substantially more
    # reliable. If a particular imported face is numerically troublesome, retry
    # that groove at a reduced depth and skip only the failed groove.
    current = target
    accepted_top = 0
    accepted_bottom = 0
    skipped = 0

    def apply_one(shape, x, y, z, inward_normal):
        before = shape.Volume()
        for depth in (nominal_depth, max(0.25, 0.55 * nominal_depth)):
            try:
                cutter = capsule_cutter(x, y, z, inward_normal, depth)
                trial = shape.cut(cutter)
                after = trial.Volume()
                if before - after <= 1.0e-7:
                    continue
                if not list(trial.Solids()):
                    continue
                # Require validity when the incoming STEP solid is valid. If the
                # source itself is flagged invalid, volume reduction and solid
                # retention are the safer acceptance criteria.
                if shape.isValid() and not trial.isValid():
                    continue
                return trial, True
            except Exception:
                continue
        return shape, False

    for z in top_positions:
        current, ok = apply_one(current, top_x, top_y, z, -1)
        if ok:
            accepted_top += 1
        else:
            skipped += 1

    for z in bottom_positions:
        current, ok = apply_one(current, bottom_x, bottom_y, z, 1)
        if ok:
            accepted_bottom += 1
        else:
            skipped += 1

    removed_volume = original_volume - current.Volume()
    if accepted_top == 0 or accepted_bottom == 0 or removed_volume <= 1.0e-6:
        raise ValueError("Unable to create valid slot grooves on both rails")

    output_solids = [current if i == target_index else solid
                     for i, solid in enumerate(solids)]
    result = cq.Compound.makeCompound(output_solids)

    print("Principal solid index:", target_index)
    print("Original target valid:", original_valid)
    print("Top/bottom rail Y:", top_y, bottom_y)
    print("Slot length/width/depth:", slot_length, slot_width, nominal_depth)
    print("Accepted top slots:", accepted_top, "of", len(top_positions))
    print("Accepted bottom slots:", accepted_bottom, "of", len(bottom_positions))
    print("Skipped cutters:", skipped)
    print("Removed volume:", removed_volume)
    print("Result valid:", result.isValid())
    return result