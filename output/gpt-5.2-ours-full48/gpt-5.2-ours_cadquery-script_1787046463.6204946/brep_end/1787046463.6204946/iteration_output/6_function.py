def my_cad_function(args):
    import cadquery as cq
    import os, math

    # --- Parameters (mm) ---
    W = 200.0      # 20 cm
    H = 100.0      # 10 cm
    DEPTH = 30.0   # 3 cm
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

    # --- Choose rear side along Z-extreme (assumes Z is front/back as in prior run) ---
    tol = 2.0  # mm band
    area_zmin = 0.0
    area_zmax = 0.0
    n_zmin = 0
    n_zmax = 0

    for f in shp.Faces():
        try:
            fb = f.BoundingBox()
            a = float(f.Area())
            gt = f.geomType()
        except Exception:
            continue
        # Favor planar-like extreme faces for a rear wall decision
        if gt == "PLANE":
            if fb.zmin <= bbox.zmin + tol:
                area_zmin += a
                n_zmin += 1
            if fb.zmax >= bbox.zmax - tol:
                area_zmax += a
                n_zmax += 1

    # Fallback if no planar faces found at extremes
    if (n_zmin + n_zmax) == 0:
        for f in shp.Faces():
            try:
                fb = f.BoundingBox()
                a = float(f.Area())
            except Exception:
                continue
            if fb.zmin <= bbox.zmin + tol:
                area_zmin += a
                n_zmin += 1
            if fb.zmax >= bbox.zmax - tol:
                area_zmax += a
                n_zmax += 1

    rear_is_zmax = area_zmax > area_zmin
    rear_z = bbox.zmax if rear_is_zmax else bbox.zmin
    n_in = cq.Vector(0, 0, -1) if rear_is_zmax else cq.Vector(0, 0, 1)

    print(f"Extreme planar faces: zmin_count={n_zmin} area={area_zmin:.1f} | zmax_count={n_zmax} area={area_zmax:.1f}")
    print(f"Chosen rear side: {'zmax' if rear_is_zmax else 'zmin'} at z={rear_z:.3f}")
    print(f"Cut normal inward: ({n_in.x:.1f},{n_in.y:.1f},{n_in.z:.1f})")

    # --- Placement: centered in X; bottom margin ~= side margin (in Y) ---
    x_center = (bbox.xmin + bbox.xmax) / 2.0

    side_margin = (bbox.xlen - W) / 2.0
    if side_margin < 0:
        print(f"WARNING: Opening width {W} exceeds model xlen {bbox.xlen:.2f}. Clamping side_margin to 0.")
        side_margin = 0.0

    bottom_margin = side_margin
    y_center = bbox.ymin + bottom_margin + H / 2.0
    y_center = max(y_center, bbox.ymin + H / 2.0 + 1.0)
    y_center = min(y_center, bbox.ymax - H / 2.0 - 1.0)

    print(f"Computed side_margin={side_margin:.2f} -> bottom_margin={bottom_margin:.2f}")
    print(f"Opening center: x={x_center:.2f}, y={y_center:.2f}")

    # --- Idempotency check: detect existing pocket bottom face ---
    # Expected rounded-rectangle area
    Aexp = (W - 2 * R) * (H - 2 * R) + math.pi * R * R
    # Expected pocket bottom center point
    z_bottom = rear_z + (DEPTH if not rear_is_zmax else -DEPTH)
    pexp = cq.Vector(x_center, y_center, z_bottom)

    pos_tol = 10.0  # mm
    z_tol = 1.5     # mm
    area_tol = 0.45 # 45%

    found_existing = False
    for f in shp.Faces():
        try:
            if f.geomType() != "PLANE":
                continue
            fc = f.Center()
            a = float(f.Area())
        except Exception:
            continue

        if abs(fc.z - pexp.z) > z_tol:
            continue
        if (fc.sub(pexp)).Length > pos_tol:
            continue
        if abs(a - Aexp) / Aexp > area_tol:
            continue

        # Also ensure face normal roughly opposes inward direction (i.e., it's a pocket bottom)
        try:
            n = f.normalAt().normalized()
            if n.dot(n_in) > -0.5:  # should be mostly opposite to n_in
                continue
        except Exception:
            pass

        found_existing = True
        print(f"Detected existing rear pocket bottom face: area={a:.1f} (expected~{Aexp:.1f}), center=({fc.x:.2f},{fc.y:.2f},{fc.z:.2f})")
        break

    if found_existing:
        print("Pocket appears to already exist; returning model unchanged.")
        return model

    # --- Create cutter and cut pocket ---
    eps_out = 0.2
    z_outside = rear_z + (eps_out if rear_is_zmax else -eps_out)
    cutter_len = DEPTH + eps_out

    plane = cq.Plane(
        origin=cq.Vector(x_center, y_center, z_outside),
        normal=n_in,
        xDir=cq.Vector(1, 0, 0),
    )

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
    print(f"Applied rear pocket: {W}x{H} mm, corner R{R} mm, depth {DEPTH} mm (eps_out={eps_out}, cutter_len={cutter_len})")
    return result
