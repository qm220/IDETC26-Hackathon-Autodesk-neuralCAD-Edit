def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    base_shape = model.val()

    solids = base_shape.Solids()
    print(f"Imported model: valid={base_shape.isValid()}, solids={len(solids)}, faces={len(base_shape.Faces())}")

    # Identify the broad radiator body by favoring large Y/Z spans and a relatively
    # shallow X span. This avoids using the fan hubs, hose ports, cap, or pegs to
    # establish the top and bottom tank surfaces.
    def radiator_score(solid):
        bb = solid.BoundingBox()
        return (bb.ylen * bb.zlen) / max(bb.xlen, 1.0)

    ranked = sorted(solids, key=radiator_score, reverse=True)
    body = ranked[0]
    body_bb = body.BoundingBox()

    print(
        "Selected radiator reference body bbox: "
        f"X=({body_bb.xmin:.2f},{body_bb.xmax:.2f}), "
        f"Y=({body_bb.ymin:.2f},{body_bb.ymax:.2f}), "
        f"Z=({body_bb.zmin:.2f},{body_bb.zmax:.2f})"
    )
    for index, solid in enumerate(ranked[:5]):
        bb = solid.BoundingBox()
        print(
            f"Candidate {index}: volume={solid.Volume():.2f}, "
            f"bbox=({bb.xlen:.2f}, {bb.ylen:.2f}, {bb.zlen:.2f}), "
            f"score={radiator_score(solid):.2f}"
        )

    x_center = (body_bb.xmin + body_bb.xmax) * 0.5
    z_center = (body_bb.zmin + body_bb.zmax) * 0.5

    # Straight slots run in X and are patterned across global Z. Keep them well
    # inside the tank's front/rear edges and use a shallow, non-through recess.
    slot_length = max(12.0, min(34.0, body_bb.xlen * 0.58))
    slot_width = max(3.5, min(6.0, body_bb.zlen * 0.012))
    slot_depth = max(1.2, min(2.5, body_bb.ylen * 0.007))
    overlap = 0.35

    end_margin = max(18.0, body_bb.zlen * 0.055)
    usable_zmin = body_bb.zmin + end_margin
    usable_zmax = body_bb.zmax - end_margin
    usable_span = usable_zmax - usable_zmin
    nominal_pitch = max(20.0, min(27.0, body_bb.zlen / 19.0))
    pattern_count = max(7, int(usable_span / nominal_pitch) + 1)
    pitch = usable_span / float(pattern_count - 1)
    z_positions = [usable_zmin + i * pitch for i in range(pattern_count)]

    def capsule_cutter(xc, zc, y0, height):
        radius = slot_width * 0.5
        straight_length = slot_length - slot_width
        xmin = xc - straight_length * 0.5
        zmin = zc - radius
        center_box = cq.Solid.makeBox(
            straight_length, height, slot_width,
            cq.Vector(xmin, y0, zmin)
        )
        left_cap = cq.Solid.makeCylinder(
            radius, height,
            cq.Vector(xc - straight_length * 0.5, y0, zc),
            cq.Vector(0, 1, 0)
        )
        right_cap = cq.Solid.makeCylinder(
            radius, height,
            cq.Vector(xc + straight_length * 0.5, y0, zc),
            cq.Vector(0, 1, 0)
        )
        return center_box.fuse(left_cap, right_cap)

    cutters = []
    top_used = []
    bottom_used = []

    # Top exclusions: central filler neck/cap and the upper semantic-left (+Z)
    # mounting region. End margins also protect upper corner transitions.
    filler_clearance = max(24.0, pitch * 0.85)
    upper_left_peg_zone = body_bb.zmax - end_margin * 1.15
    for zpos in z_positions:
        if abs(zpos - z_center) < filler_clearance:
            continue
        if zpos > upper_left_peg_zone:
            continue
        cutters.append(capsule_cutter(
            x_center,
            zpos,
            body_bb.ymax - slot_depth,
            slot_depth + overlap
        ))
        top_used.append(zpos)

    # Bottom exclusions are solved independently because the lower mounting peg
    # is on the semantic-right (-Z) side.
    lower_right_peg_zone = body_bb.zmin + end_margin * 1.15
    for zpos in z_positions:
        if zpos < lower_right_peg_zone:
            continue
        cutters.append(capsule_cutter(
            x_center,
            zpos,
            body_bb.ymin - overlap,
            slot_depth + overlap
        ))
        bottom_used.append(zpos)

    print(
        f"Slot dimensions: length={slot_length:.2f}, width={slot_width:.2f}, "
        f"depth={slot_depth:.2f}, nominal pitch={pitch:.2f}"
    )
    print(f"Created {len(top_used)} top slots and {len(bottom_used)} bottom slots")

    cutter_compound = cq.Compound.makeCompound(cutters)
    edited_shape = base_shape.cut(cutter_compound)
    print(
        f"Edited model: valid={edited_shape.isValid()}, "
        f"solids={len(edited_shape.Solids())}, faces={len(edited_shape.Faces())}"
    )

    return cq.Workplane(obj=edited_shape)
