def my_cad_function(args):
    import cadquery as cq
    import os, math

    # --- Parameters (mm) ---
    W = 200.0      # opening width (X)
    H = 100.0      # opening height (vertical)
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

    # Heuristic coordinate convention for this model (based on prior render triads):
    # X = left-right, Y = vertical (up), Z = front-back.
    # Therefore, the BACK face is at an extreme of Z (zmin or zmax).

    tol = 2.0
    area_zmin = 0.0
    area_zmax = 0.0
    n_zmin = 0
    n_zmax = 0

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

    # Choose back as the Z extreme with larger total area (front likely has openings/cutouts)
    back_is_zmax = area_zmax > area_zmin
    back_z = bbox.zmax if back_is_zmax else bbox.zmin
    n_in = cq.Vector(0, 0, -1) if back_is_zmax else cq.Vector(0, 0, 1)

    print(f"Extreme-face area bands (Z): zmin_count={n_zmin} area={area_zmin:.1f} | zmax_count={n_zmax} area={area_zmax:.1f}")
    print(f"Chosen BACK side: {'zmax' if back_is_zmax else 'zmin'} at z={back_z:.3f}")
    print(f"Cut normal inward: ({n_in.x:.1f},{n_in.y:.1f},{n_in.z:.1f})")

    # --- Placement: centered in X; bottom margin ~= side margin (bottom is Ymin) ---
    x_center = (bbox.xmin + bbox.xmax) / 2.0

    side_margin = (bbox.xlen - W) / 2.0
    if side_margin < 0:
        print(f"WARNING: Opening width {W} exceeds model xlen {bbox.xlen:.2f}. Clamping side_margin to 0.")
        side_margin = 0.0

    bottom_margin = side_margin
    y_center = bbox.ymin + bottom_margin + H / 2.0

    # Keep inside model height span
    y_center = max(y_center, bbox.ymin + H / 2.0 + 1.0)
    y_center = min(y_center, bbox.ymax - H / 2.0 - 1.0)

    print(f"Computed side_margin={side_margin:.2f} -> bottom_margin={bottom_margin:.2f}")
    print(f"Opening center (x,y)=({x_center:.2f},{y_center:.2f}) on back z={back_z:.2f}")

    # --- Idempotency: detect existing pocket bottom face at back_z +/- DEPTH ---
    Aexp = (W - 2 * R) * (H - 2 * R) + math.pi * R * R
    z_bottom = back_z + (-DEPTH if back_is_zmax else DEPTH)
    pexp = cq.Vector(x_center, y_center, z_bottom)

    pos_tol_xy = 12.0
    z_tol = 1.5
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

        if abs(fc.z - pexp.z) > z_tol:
            continue
        if abs(fc.x - pexp.x) > pos_tol_xy or abs(fc.y - pexp.y) > pos_tol_xy:
            continue
        if abs(a - Aexp) / Aexp > area_tol:
            continue

        found_existing = True
        print(f"Detected existing back pocket bottom face: area={a:.1f} (expected~{Aexp:.1f}), center=({fc.x:.2f},{fc.y:.2f},{fc.z:.2f})")
        break

    if found_existing:
        print("Pocket appears to already exist on the back; returning model unchanged.")
        return wp

    # --- Build cutter: sketch in XY plane on a plane just outside back surface; extrude inward along Z ---
    eps_out = 0.4
    z_outside = back_z + (eps_out if back_is_zmax else -eps_out)
    cutter_len = DEPTH + eps_out

    plane = cq.Plane(
        origin=cq.Vector(x_center, y_center, z_outside),
        normal=n_in,
        xDir=cq.Vector(1, 0, 0),
    )

    cutter = (
        cq.Workplane(plane)
        .sketch()
        .rect(W, H)          # W along X, H along Y (vertical)
        .vertices()
        .fillet(R)
        .finalize()
        .extrude(cutter_len) # along plane normal (inward)
    )

    result = wp.cut(cutter)
    print(f"Applied BACK opening/pocket: {W}x{H} mm, corner R{R} mm, depth {DEPTH} mm (back={'zmax' if back_is_zmax else 'zmin'})")
    return result
