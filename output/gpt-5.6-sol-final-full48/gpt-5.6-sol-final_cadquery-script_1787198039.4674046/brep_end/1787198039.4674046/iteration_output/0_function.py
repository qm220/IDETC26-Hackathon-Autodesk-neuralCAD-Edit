def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported
    solids = list(root.Solids())
    if not solids:
        raise ValueError("The input STEP file contains no solids")

    # The perimeter housing, radiator support, and stationary fan guards form
    # the highly detailed principal solid. The remaining solids are blades,
    # fittings, mounts, and the service cap and must remain unchanged.
    target_index = max(range(len(solids)), key=lambda i: len(solids[i].Faces()))
    target = solids[target_index]
    target_bb = target.BoundingBox()

    def long_horizontal_faces(shape):
        candidates = []
        y_tol = max(1.0e-4, target_bb.ylen * 1.0e-5)
        for face in shape.Faces():
            try:
                if face.geomType() != "PLANE":
                    continue
                bb = face.BoundingBox()
                if bb.ylen <= y_tol and bb.zlen >= 0.35 * target_bb.zlen and bb.xlen > 0.5:
                    candidates.append((face, bb))
            except Exception:
                pass
        return candidates

    horizontal = long_horizontal_faces(target)
    if len(horizontal) < 2:
        raise ValueError("Could not identify the long exterior top and bottom rail faces")

    top_face, top_bb = max(horizontal, key=lambda item: (item[1].ymax, item[0].Area()))
    bottom_face, bottom_bb = min(horizontal, key=lambda item: (item[1].ymin, -item[0].Area()))

    top_y = 0.5 * (top_bb.ymin + top_bb.ymax)
    bottom_y = 0.5 * (bottom_bb.ymin + bottom_bb.ymax)

    # Use the common longitudinal region and the narrower of the two rail faces
    # so the top and bottom patterns use matching capsule dimensions.
    z_min = max(top_bb.zmin, bottom_bb.zmin)
    z_max = min(top_bb.zmax, bottom_bb.zmax)
    if z_max <= z_min:
        z_min = min(top_bb.zmin, bottom_bb.zmin)
        z_max = max(top_bb.zmax, bottom_bb.zmax)
    z_span = z_max - z_min

    top_x_span = top_bb.xmax - top_bb.xmin
    bottom_x_span = bottom_bb.xmax - bottom_bb.xmin
    usable_x_span = min(top_x_span, bottom_x_span)
    if usable_x_span <= 1.0:
        raise ValueError("Identified rail faces do not have sufficient transverse width")

    slot_width = max(2.5, min(9.0, 0.012 * z_span))
    transverse_margin = max(0.75 * slot_width, 0.10 * usable_x_span)
    slot_length = usable_x_span - 2.0 * transverse_margin
    slot_length = max(2.0 * slot_width, min(slot_length, 0.82 * usable_x_span))

    # A shallow blind cosmetic/ventilation recess preserves the rail wall and
    # avoids opening any coolant-containing region.
    slot_depth = max(0.8, min(2.5, 0.025 * target_bb.ylen))
    outside_overlap = min(0.25, 0.12 * slot_depth)

    top_x = 0.5 * (top_bb.xmin + top_bb.xmax)
    bottom_x = 0.5 * (bottom_bb.xmin + bottom_bb.xmax)

    end_margin = max(2.2 * slot_width, 0.055 * z_span)
    pattern_min = z_min + end_margin
    pattern_max = z_max - end_margin
    pitch = max(3.0 * slot_width, z_span / 19.0)
    z_center = 0.5 * (z_min + z_max)

    # Project protruding service/mount solids onto each rail to establish
    # automatic keep-out intervals. This normally detects the centered fill
    # cap on top and the hose/mount geometry near the lower rail ends.
    top_keepouts = []
    bottom_keepouts = []
    clearance = max(slot_width, 0.018 * z_span)
    proximity = max(20.0, 0.06 * z_span)

    for i, solid in enumerate(solids):
        if i == target_index:
            continue
        bb = solid.BoundingBox()
        overlaps_top_x = bb.xmax >= top_bb.xmin and bb.xmin <= top_bb.xmax
        overlaps_bottom_x = bb.xmax >= bottom_bb.xmin and bb.xmin <= bottom_bb.xmax

        if (overlaps_top_x and bb.ymax > top_y + 0.25 and
                bb.ymin < top_y + proximity):
            top_keepouts.append((bb.zmin - clearance, bb.zmax + clearance))

        if (overlaps_bottom_x and bb.ymin < bottom_y - 0.25 and
                bb.ymax > bottom_y - proximity):
            bottom_keepouts.append((bb.zmin - clearance, bb.zmax + clearance))

    # Explicitly reserve the central top service area even if the cap is
    # represented with an unusual STEP bounding box.
    central_clearance = max(2.2 * slot_width, 0.035 * z_span)
    top_keepouts.append((z_center - central_clearance,
                         z_center + central_clearance))

    def patterned_positions(keepouts):
        positions = []
        half_width = 0.5 * slot_width
        max_steps = int(z_span / pitch) + 3
        for k in range(-max_steps, max_steps + 1):
            z = z_center + k * pitch
            if z < pattern_min or z > pattern_max:
                continue
            blocked = any((z + half_width) > lo and (z - half_width) < hi
                          for lo, hi in keepouts)
            if not blocked:
                positions.append(z)
        return sorted(positions)

    top_positions = patterned_positions(top_keepouts)
    bottom_positions = patterned_positions(bottom_keepouts)

    # Keep sensible patterns even if conservative projected keep-outs happen
    # to consume an entire side because of a coarse component bounding box.
    if len(top_positions) < 4:
        top_positions = patterned_positions([
            (z_center - central_clearance, z_center + central_clearance)
        ])
    if len(bottom_positions) < 4:
        bottom_positions = patterned_positions([])

    cutters = []

    # Top plane normal points inward along -Y.
    for z in top_positions:
        plane = cq.Plane(
            origin=(top_x, top_y + outside_overlap, z),
            xDir=(1, 0, 0),
            normal=(0, -1, 0)
        )
        cutter = (cq.Workplane(plane)
                  .slot2D(slot_length, slot_width, 0)
                  .extrude(slot_depth + 2.0 * outside_overlap)
                  .val())
        cutters.append(cutter)

    # Bottom plane normal points inward along +Y.
    for z in bottom_positions:
        plane = cq.Plane(
            origin=(bottom_x, bottom_y - outside_overlap, z),
            xDir=(1, 0, 0),
            normal=(0, 1, 0)
        )
        cutter = (cq.Workplane(plane)
                  .slot2D(slot_length, slot_width, 0)
                  .extrude(slot_depth + 2.0 * outside_overlap)
                  .val())
        cutters.append(cutter)

    if not cutters:
        raise ValueError("No slot cutters were generated")

    cutter_compound = cq.Compound.makeCompound(cutters)
    original_volume = target.Volume()
    modified_target = target.cut(cutter_compound)

    if not modified_target.isValid():
        raise ValueError("Slot subtraction produced an invalid housing solid")
    if modified_target.Volume() >= original_volume - 1.0e-6:
        raise ValueError("Generated slot cutters did not intersect the plastic rails")

    output_solids = []
    for i, solid in enumerate(solids):
        output_solids.append(modified_target if i == target_index else solid)

    result = cq.Compound.makeCompound(output_solids)
    print("Principal solid index:", target_index)
    print("Top rail Y / bottom rail Y:", top_y, bottom_y)
    print("Slot length, width, depth:", slot_length, slot_width, slot_depth)
    print("Top slot count / bottom slot count:", len(top_positions), len(bottom_positions))
    print("Removed volume:", original_volume - modified_target.Volume())
    print("Result valid:", result.isValid())
    return result