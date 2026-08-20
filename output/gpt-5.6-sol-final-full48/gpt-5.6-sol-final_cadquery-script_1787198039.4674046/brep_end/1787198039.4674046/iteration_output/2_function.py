def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported
    solids = list(root.Solids())
    if not solids:
        raise ValueError("The input STEP file contains no solids")

    target_index = max(range(len(solids)), key=lambda i: len(solids[i].Faces()))
    target = solids[target_index]
    target_bb = target.BoundingBox()
    original_volume = target.Volume()

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

    common_x_min = max(top_bb.xmin, bottom_bb.xmin)
    common_x_max = min(top_bb.xmax, bottom_bb.xmax)
    common_x_span = common_x_max - common_x_min
    if z_span <= 10.0 or common_x_span <= 2.0:
        raise ValueError("The rail surfaces are too small for a slot pattern")

    top_x = 0.5 * (top_bb.xmin + top_bb.xmax)
    bottom_x = 0.5 * (bottom_bb.xmin + bottom_bb.xmax)
    slot_width = max(2.0, min(6.0, 0.009 * z_span, 0.18 * common_x_span))
    slot_length = max(2.2 * slot_width, min(0.56 * common_x_span,
                                           common_x_span - 2.2 * slot_width))
    nominal_depth = max(0.35, min(0.80, 0.010 * target_bb.ylen))
    overlap = 0.12

    z_center = 0.5 * (z_min + z_max)
    end_margin = max(2.5 * slot_width, 0.065 * z_span)
    pattern_min = z_min + end_margin
    pattern_max = z_max - end_margin
    desired_count = 13
    pitch = (pattern_max - pattern_min) / float(desired_count - 1)
    base_positions = [pattern_min + i * pitch for i in range(desired_count)]

    clearance = max(1.5 * slot_width, 0.012 * z_span)
    proximity = max(12.0, 0.045 * z_span)
    central_clearance = max(2.8 * slot_width, 0.038 * z_span)
    top_keepouts = [(z_center - central_clearance, z_center + central_clearance)]
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
    if len(top_positions) < 5:
        top_positions = filter_positions([top_keepouts[0]])
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

    def apply_one(shape, x, y, z, inward_normal):
        before = shape.Volume()
        for depth in (nominal_depth, max(0.25, 0.55 * nominal_depth)):
            try:
                trial = shape.cut(capsule_cutter(x, y, z, inward_normal, depth))
                if before - trial.Volume() <= 1.0e-7 or not list(trial.Solids()):
                    continue
                if shape.isValid() and not trial.isValid():
                    continue
                return trial, True
            except Exception:
                pass
        return shape, False

    current = target
    accepted_top = 0
    accepted_bottom = 0
    for z in top_positions:
        current, ok = apply_one(current, top_x, top_y, z, -1)
        accepted_top += int(ok)
    for z in bottom_positions:
        current, ok = apply_one(current, bottom_x, bottom_y, z, 1)
        accepted_bottom += int(ok)

    if accepted_top == 0 or accepted_bottom == 0 or original_volume - current.Volume() <= 1.0e-6:
        raise ValueError("Unable to create slot grooves on both rails")

    output_solids = [current if i == target_index else solid
                     for i, solid in enumerate(solids)]
    return cq.Compound.makeCompound(output_solids)