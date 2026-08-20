def my_cad_function(args):
    import os

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported

    faces = root.Faces()
    solids = root.Solids()
    print("Loaded STEP:", input_file)
    print("Valid:", root.isValid(), "solids:", len(solids), "faces:", len(faces))

    # Inspect and bind the grounded STEP face indices to actual geometry.
    target_indices = [45, 46, 297, 307, 332, 351, 361, 362, 365, 366, 368, 370]
    for idx in target_indices:
        if idx >= len(faces):
            print("FACE", idx, "is unavailable")
            continue
        face = faces[idx]
        bb = face.BoundingBox()
        c = face.Center()
        try:
            gt = face.geomType()
        except Exception:
            gt = "unknown"
        print(
            "FACE %d type=%s center=(%.6f, %.6f, %.6f) "
            "bbox=(%.6f..%.6f, %.6f..%.6f, %.6f..%.6f) area=%.6f"
            % (idx, gt, c.x, c.y, c.z,
               bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax,
               face.Area())
        )

    def same_shape(a, b):
        try:
            return a.isSame(b)
        except Exception:
            try:
                return a.hashCode() == b.hashCode()
            except Exception:
                return False

    def owner_index(face_index):
        target = faces[face_index]
        for si, solid in enumerate(solids):
            for sf in solid.Faces():
                if same_shape(target, sf):
                    return si
        return None

    # Resolve complete connected solids from the grounded faces instead of
    # assuming that imported STEP solid ordering is stable.
    cordholder_owner = owner_index(297)
    cradle_owner = owner_index(365)
    print("Cordholder FACE 297 owner solid:", cordholder_owner)
    print("Cradle FACE 365 owner solid:", cradle_owner)

    if cordholder_owner is None:
        raise RuntimeError("Could not bind FACE 297 to the Cordholder solid")
    if cradle_owner is None:
        raise RuntimeError("Could not bind FACE 365 to the cradle solid")
    if cordholder_owner == cradle_owner:
        raise RuntimeError("Cordholder and cradle unexpectedly resolved to the same solid")

    # Derive the housing midpoint from the two grounded housing end faces.
    y_end_high = faces[45].Center().y
    y_end_low = faces[46].Center().y
    y_mid = 0.5 * (y_end_high + y_end_low)

    # Derive the common ground plane from the two existing foot seating faces.
    z_ground_1 = faces[332].Center().z
    z_ground_2 = faces[351].Center().z
    z_ground = 0.5 * (z_ground_1 + z_ground_2)
    print("Housing end Y values:", y_end_low, y_end_high, "midplane:", y_mid)
    print("Foot support Z values:", z_ground_1, z_ground_2, "datum:", z_ground)

    cradle = solids[cradle_owner]
    cradle_bb = cradle.BoundingBox()
    print(
        "Original cradle bbox: x %.6f..%.6f, y %.6f..%.6f, z %.6f..%.6f"
        % (cradle_bb.xmin, cradle_bb.xmax, cradle_bb.ymin, cradle_bb.ymax,
           cradle_bb.zmin, cradle_bb.zmax)
    )

    # Remove every point below the authoritative foot support elevation.  The
    # cutter is deliberately oversized in X/Y and terminates at z_ground so
    # the resulting cradle contact faces are planar and exactly coplanar with
    # the existing feet.
    root_bb = root.BoundingBox()
    margin = 100.0
    cutter_x = (root_bb.xmax - root_bb.xmin) + 2.0 * margin
    cutter_y = (root_bb.ymax - root_bb.ymin) + 2.0 * margin
    cutter_bottom = min(root_bb.zmin, cradle_bb.zmin) - margin
    cutter_height = z_ground - cutter_bottom
    cutter = (
        cq.Workplane("XY")
        .box(cutter_x, cutter_y, cutter_height)
        .translate((
            0.5 * (root_bb.xmin + root_bb.xmax),
            0.5 * (root_bb.ymin + root_bb.ymax),
            cutter_bottom + 0.5 * cutter_height,
        ))
        .val()
    )

    trimmed_cradle = cradle.cut(cutter)
    if not trimmed_cradle.isValid():
        raise RuntimeError("The trimmed original cradle is invalid")

    # Duplicate the complete cradle, including both radius-7.62 pin bores, by
    # mirroring it about the longitudinal housing midplane y=y_mid.
    mirrored_cradle = trimmed_cradle.mirror("XZ", (0.0, y_mid, 0.0))
    if not mirrored_cradle.isValid():
        raise RuntimeError("The mirrored cradle is invalid")

    tbb = trimmed_cradle.BoundingBox()
    mbb = mirrored_cradle.BoundingBox()
    print(
        "Trimmed original cradle bbox: y %.6f..%.6f, z %.6f..%.6f"
        % (tbb.ymin, tbb.ymax, tbb.zmin, tbb.zmax)
    )
    print(
        "New mirrored cradle bbox: y %.6f..%.6f, z %.6f..%.6f"
        % (mbb.ymin, mbb.ymax, mbb.zmin, mbb.zmax)
    )
    print(
        "End clearances: original %.6f, mirrored %.6f"
        % (y_end_high - tbb.ymax, mbb.ymin - y_end_low)
    )

    # Retain all original assembly solids except the complete Cordholder body
    # and the untrimmed cradle. Add the trimmed original and mirrored cradle as
    # separate assembly solids so their pivot interfaces remain intact.
    output_shapes = []
    for si, solid in enumerate(solids):
        if si == cordholder_owner:
            print("Removed Cordholder solid", si)
            continue
        if si == cradle_owner:
            continue
        output_shapes.append(solid)

    output_shapes.append(trimmed_cradle)
    output_shapes.append(mirrored_cradle)
    result = cq.Compound.makeCompound(output_shapes)

    print(
        "Result valid:", result.isValid(),
        "solids:", len(result.Solids()),
        "faces:", len(result.Faces())
    )
    if not result.isValid():
        raise RuntimeError("Final edited assembly is invalid")
    return result