def my_cad_function(args):
    import cadquery as cq
    import os

    # --- Parameters (mm) ---
    W = 200.0      # 20 cm (left-right)
    H = 100.0      # 10 cm (up-down)
    DEPTH = 30.0   # 3 cm pocket depth into machine
    R = 10.0       # 1 cm corner radius

    if "input_file" not in args:
        raise ValueError("Expected args['input_file'] for edit operation")

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shp = model.val() if hasattr(model, "val") else model
    if shp is None:
        raise ValueError("Failed to import STEP shape")

    bbox = shp.BoundingBox()
    c = bbox.center
    print(f"BBox: xmin={bbox.xmin:.3f} xmax={bbox.xmax:.3f} xlen={bbox.xlen:.3f}")
    print(f"      ymin={bbox.ymin:.3f} ymax={bbox.ymax:.3f} ylen={bbox.ylen:.3f}")
    print(f"      zmin={bbox.zmin:.3f} zmax={bbox.zmax:.3f} zlen={bbox.zlen:.3f}")
    print(f"BBox center: ({c.x:.3f}, {c.y:.3f}, {c.z:.3f})")

    # --- Determine which Z-extreme is the rear by comparing total face area near each extreme ---
    tol = 2.0  # mm
    faces_zmin = []
    faces_zmax = []
    area_zmin = 0.0
    area_zmax = 0.0

    for f in shp.Faces():
        try:
            fb = f.BoundingBox()
            a = float(f.Area())
        except Exception:
            continue
        if fb.zmin <= bbox.zmin + tol:
            faces_zmin.append((f, fb, a))
            area_zmin += a
        if fb.zmax >= bbox.zmax - tol:
            faces_zmax.append((f, fb, a))
            area_zmax += a

    print(f"Faces touching zmin (<= zmin+{tol}): {len(faces_zmin)} total_area={area_zmin:.1f}")
    print(f"Faces touching zmax (>= zmax-{tol}): {len(faces_zmax)} total_area={area_zmax:.1f}")

    # Heuristic: the rear is usually the more closed/continuous side, often having larger summed area.
    # If ambiguous, default to zmin.
    rear_is_zmax = area_zmax > area_zmin
    rear_z = bbox.zmax if rear_is_zmax else bbox.zmin

    # Cut direction inward along Z
    n_in = cq.Vector(0, 0, -1) if rear_is_zmax else cq.Vector(0, 0, 1)

    print(f"Chosen rear side: {'zmax' if rear_is_zmax else 'zmin'} at z={rear_z:.3f}")
    print(f"Cut normal inward: ({n_in.x:.1f},{n_in.y:.1f},{n_in.z:.1f})")

    # --- Placement ---
    # Center horizontally about overall width (X). Place low in Y with bottom margin ~= side margin.
    x_center = (bbox.xmin + bbox.xmax) / 2.0

    side_margin = (bbox.xlen - W) / 2.0
    if side_margin < 0:
        print(f"WARNING: Opening width {W} exceeds model xlen {bbox.xlen:.2f}. Clamping margins.")
        side_margin = 0.0

    bottom_margin = side_margin
    y_center = bbox.ymin + bottom_margin + H / 2.0

    # Keep the feature inside the overall height
    y_min_allowed = bbox.ymin + H / 2.0 + 1.0
    y_max_allowed = bbox.ymax - H / 2.0 - 1.0
    if y_center < y_min_allowed:
        y_center = y_min_allowed
    if y_center > y_max_allowed:
        y_center = y_max_allowed

    print(f"Computed side_margin={side_margin:.2f} -> bottom_margin={bottom_margin:.2f}")
    print(f"Opening center: x={x_center:.2f}, y={y_center:.2f}")

    # Start the cutter slightly outside the rear extreme so it reliably pierces the rear panel
    outside_offset = 1.0
    z_outside = rear_z + (outside_offset if rear_is_zmax else -outside_offset)

    plane = cq.Plane(origin=cq.Vector(x_center, y_center, z_outside), normal=n_in, xDir=cq.Vector(1, 0, 0))

    # Make the cutter slightly longer than DEPTH to ensure it fully passes through any thin rear panel
    cutter_len = DEPTH + 2.0

    cutter = (
        cq.Workplane(plane)
        .sketch()
        .rect(W, H)
        .vertices()
        .fillet(R)
        .finalize()
        .extrude(cutter_len)
    )

    result = model.cut(cutter)
    print(f"Applied rear opening/pocket cut: {W}x{H} mm, corner R{R} mm, depth {DEPTH} mm (cutter_len={cutter_len} mm)")

    return result
