def my_cad_function(args):
    import cadquery as cq
    import os, math

    # --- Parameters (mm) ---
    W = 200.0      # width (left-right)
    H = 100.0      # height (bottom-top)
    DEPTH = 30.0   # pocket depth into machine
    R = 10.0       # corner radius

    if "input_file" not in args:
        raise ValueError("Expected args['input_file'] for edit operation")

    input_file = os.path.expanduser(args["input_file"])
    imp = cq.importers.importStep(input_file)

    # Normalize to both: a Workplane for ops + a Shape for inspection
    if isinstance(imp, cq.Workplane):
        wp = imp
        shp = imp.val()
    else:
        shp = imp
        wp = cq.Workplane(obj=shp)

    if shp is None:
        raise ValueError("Failed to import STEP shape")

    bbox = shp.BoundingBox()
    c = bbox.center
    print(f"BBox: xmin={bbox.xmin:.3f} xmax={bbox.xmax:.3f} xlen={bbox.xlen:.3f}")
    print(f"      ymin={bbox.ymin:.3f} ymax={bbox.ymax:.3f} ylen={bbox.ylen:.3f}")
    print(f"      zmin={bbox.zmin:.3f} zmax={bbox.zmax:.3f} zlen={bbox.zlen:.3f}")
    print(f"BBox center: ({c.x:.3f}, {c.y:.3f}, {c.z:.3f})")

    # --- Decide which Y extreme is the REAR ---
    # In the last iteration, Z was mistakenly treated as front/back.
    # Here we treat Y as front/back and Z as vertical.
    tol = 2.0
    area_ymin = 0.0
    area_ymax = 0.0
    n_ymin = 0
    n_ymax = 0

    for f in shp.Faces():
        try:
            fb = f.BoundingBox()
            a = float(f.Area())
        except Exception:
            continue
        if fb.ymin <= bbox.ymin + tol:
            area_ymin += a
            n_ymin += 1
        if fb.ymax >= bbox.ymax - tol:
            area_ymax += a
            n_ymax += 1

    rear_is_ymax = area_ymax > area_ymin
    rear_y = bbox.ymax if rear_is_ymax else bbox.ymin
    n_in = cq.Vector(0, -1, 0) if rear_is_ymax else cq.Vector(0, 1, 0)

    print(f"Extreme-face area bands: ymin_count={n_ymin} area={area_ymin:.1f} | ymax_count={n_ymax} area={area_ymax:.1f}")
    print(f"Chosen rear side: {'ymax' if rear_is_ymax else 'ymin'} at y={rear_y:.3f}")
    print(f"Cut normal inward: ({n_in.x:.1f},{n_in.y:.1f},{n_in.z:.1f})")

    # --- Placement: centered in X; bottom margin ~= side margin (bottom is Zmin) ---
    x_center = (bbox.xmin + bbox.xmax) / 2.0

    side_margin = (bbox.xlen - W) / 2.0
    if side_margin < 0:
        print(f"WARNING: Opening width {W} exceeds model xlen {bbox.xlen:.2f}. Clamping side_margin to 0.")
        side_margin = 0.0

    bottom_margin = side_margin
    z_center = bbox.zmin + bottom_margin + H / 2.0

    # Keep inside the model's Z span
    z_center = max(z_center, bbox.zmin + H / 2.0 + 1.0)
    z_center = min(z_center, bbox.zmax - H / 2.0 - 1.0)

    print(f"Computed side_margin={side_margin:.2f} -> bottom_margin={bottom_margin:.2f}")
    print(f"Opening center (x,z)=({x_center:.2f},{z_center:.2f}) on rear y={rear_y:.2f}")

    # --- Idempotency: detect existing pocket bottom face at rear_y +/- DEPTH ---
    Aexp = (W - 2 * R) * (H - 2 * R) + math.pi * R * R
    y_bottom = rear_y + (-DEPTH if rear_is_ymax else DEPTH)
    pexp = cq.Vector(x_center, y_bottom, z_center)

    pos_tol_xz = 12.0
    y_tol = 1.5
    area_tol = 0.50

    found_existing = False
    for f in shp.Faces():
        try:
            if f.geomType() != "PLANE":
                continue
            fc = f.Center()
            a = float(f.Area())
        except Exception:
            continue

        if abs(fc.y - pexp.y) > y_tol:
            continue
        if abs(fc.x - pexp.x) > pos_tol_xz or abs(fc.z - pexp.z) > pos_tol_xz:
            continue
        if abs(a - Aexp) / Aexp > area_tol:
            continue

        found_existing = True
        print(f"Detected existing rear pocket bottom face: area={a:.1f} (expected~{Aexp:.1f}), center=({fc.x:.2f},{fc.y:.2f},{fc.z:.2f})")
        break

    if found_existing:
        print("Pocket appears to already exist; returning model unchanged.")
        return wp

    # --- Build cutter: sketch in XZ plane on a plane just outside rear surface; extrude inward along Y ---
    eps_out = 0.4
    y_outside = rear_y + (eps_out if rear_is_ymax else -eps_out)
    cutter_len = DEPTH + eps_out

    # Plane's x axis along +X; y axis in plane along +Z (by choosing xDir as +X with normal +/-Y)
    plane = cq.Plane(
        origin=cq.Vector(x_center, y_outside, z_center),
        normal=n_in,
        xDir=cq.Vector(1, 0, 0),
    )

    cutter = (
        cq.Workplane(plane)
        .sketch()
        .rect(W, H)           # W along plane X, H along plane Y (which corresponds to global Z)
        .vertices()
        .fillet(R)
        .finalize()
        .extrude(cutter_len)
    )

    result = wp.cut(cutter)
    print(f"Applied rear opening/pocket: {W}x{H} mm, corner R{R} mm, depth {DEPTH} mm (rear={'ymax' if rear_is_ymax else 'ymin'})")
    return result
