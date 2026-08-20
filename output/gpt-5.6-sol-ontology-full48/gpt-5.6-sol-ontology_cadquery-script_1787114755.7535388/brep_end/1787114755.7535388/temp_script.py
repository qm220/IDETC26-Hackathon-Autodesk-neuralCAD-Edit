def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    base_shape = model.val()

    print(f"Loaded STEP: {input_file}")
    print(f"Initial valid: {base_shape.isValid()}")
    print(f"Initial solids: {len(base_shape.Solids())}")
    print(f"Initial faces: {len(base_shape.Faces())}")
    print(f"Initial volume: {base_shape.Volume():.6f} mm^3")

    # Inspect and bind the planning FACE N references to the imported topology.
    faces = base_shape.Faces()
    target_indices = {14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 28}
    for index, face in enumerate(faces):
        if index in target_indices:
            bb = face.BoundingBox()
            c = face.Center()
            print(
                f"FACE {index}: type={face.geomType()}, "
                f"center=({c.x:.6f},{c.y:.6f},{c.z:.6f}), "
                f"bbox=({bb.xmin:.6f}..{bb.xmax:.6f}, "
                f"{bb.ymin:.6f}..{bb.ymax:.6f}, "
                f"{bb.zmin:.6f}..{bb.zmax:.6f})"
            )

    # Geometrically locate the two capsule-shaped blind-pocket floors rather
    # than relying solely on STEP face ordering. Their bounds establish the
    # existing slot perimeter that must be preserved.
    floor_candidates = []
    for index, face in enumerate(faces):
        bb = face.BoundingBox()
        if (
            face.geomType() == "PLANE"
            and bb.xlen > 17.5 and bb.xlen < 18.5
            and bb.ylen > 47.5 and bb.ylen < 48.5
            and bb.zlen < 1.0e-4
            and (abs(bb.zmin + 10.0) < 0.05 or abs(bb.zmin + 32.0) < 0.05)
        ):
            floor_candidates.append((index, face, bb))
            print(f"Bound slot floor geometrically to FACE {index} at z={bb.zmin:.6f}")

    if floor_candidates:
        x_min = min(item[2].xmin for item in floor_candidates)
        x_max = max(item[2].xmax for item in floor_candidates)
        y_min = min(item[2].ymin for item in floor_candidates)
        y_max = max(item[2].ymax for item in floor_candidates)
    else:
        # Grounded dimensions from F007/F008, used only if topology recognition
        # is unavailable in the imported STEP representation.
        x_min, x_max = 104.0, 122.0
        y_min, y_max = 31.0, 79.0
        print("Warning: slot floors were not recognized; using grounded F007/F008 bounds")

    slot_width = x_max - x_min
    radius = slot_width / 2.0
    center_x = (x_min + x_max) / 2.0
    lower_center_y = y_min + radius
    upper_center_y = y_max - radius
    straight_length = upper_center_y - lower_center_y

    print(
        f"Through-slot profile: x={x_min:.6f}..{x_max:.6f}, "
        f"y={y_min:.6f}..{y_max:.6f}, radius={radius:.6f}"
    )

    # Cut beyond the complete model z bounds, ensuring removal of both blind
    # floors and the central web while retaining the existing capsule profile.
    model_bb = base_shape.BoundingBox()
    z_top = model_bb.zmax + 1.0
    z_bottom = model_bb.zmin - 1.0
    cut_depth = z_bottom - z_top

    middle = (
        cq.Workplane("XY", origin=(center_x, (lower_center_y + upper_center_y) / 2.0, z_top))
        .rect(slot_width, straight_length)
        .extrude(cut_depth)
    )
    lower_end = (
        cq.Workplane("XY", origin=(center_x, lower_center_y, z_top))
        .circle(radius)
        .extrude(cut_depth)
    )
    upper_end = (
        cq.Workplane("XY", origin=(center_x, upper_center_y, z_top))
        .circle(radius)
        .extrude(cut_depth)
    )
    cutter = middle.union(lower_end).union(upper_end)

    result_shape = base_shape.cut(cutter.val())

    print(f"Result valid: {result_shape.isValid()}")
    print(f"Result solids: {len(result_shape.Solids())}")
    print(f"Result faces: {len(result_shape.Faces())}")
    print(f"Result volume: {result_shape.Volume():.6f} mm^3")
    print(f"Removed volume: {base_shape.Volume() - result_shape.Volume():.6f} mm^3")

    if not result_shape.isValid():
        raise ValueError("Through-slot subtraction produced an invalid shape")
    if len(result_shape.Solids()) != 1:
        raise ValueError(f"Expected one connected solid, found {len(result_shape.Solids())}")

    return cq.Workplane(obj=result_shape)
