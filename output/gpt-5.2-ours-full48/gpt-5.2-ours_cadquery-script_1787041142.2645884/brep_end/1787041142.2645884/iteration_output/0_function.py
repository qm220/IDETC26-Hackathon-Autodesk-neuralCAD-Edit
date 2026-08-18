def my_cad_function(args):
    import cadquery as cq
    import os
    
    # --- Load input STEP ---
    input_file = args.get("input_file", None)
    if not input_file or not os.path.exists(os.path.expanduser(input_file)):
        raise ValueError(f"Missing or invalid args['input_file']: {input_file}")
    input_file = os.path.expanduser(input_file)

    part = cq.importers.importStep(input_file)
    shp = part.val() if hasattr(part, "val") else part

    # --- Basic diagnostics / extraction ---
    bb = shp.BoundingBox()
    xMin, xMax = bb.xmin, bb.xmax
    yMin, yMax = bb.ymin, bb.ymax
    zMin, zMax = bb.zmin, bb.zmax
    L = xMax - xMin
    W = yMax - yMin
    H = zMax - zMin

    print("=== Loaded model diagnostics ===")
    print(f"Valid: {shp.isValid()}")
    try:
        print(f"Volume: {shp.Volume():.3f} mm^3")
    except Exception as e:
        print(f"Volume unavailable: {e}")
    print(f"Faces: {len(shp.Faces())}")
    print(f"BBox X: [{xMin:.3f}, {xMax:.3f}]  L={L:.3f}")
    print(f"BBox Y: [{yMin:.3f}, {yMax:.3f}]  W={W:.3f}")
    print(f"BBox Z: [{zMin:.3f}, {zMax:.3f}]  H={H:.3f}")

    # Attempt to identify candidate top/bottom faces (by Z extrema)
    try:
        top_faces = part.faces(">Z").vals()
        bot_faces = part.faces("<Z").vals()
        print(f"Top-face candidates (">Z"): {len(top_faces)}")
        print(f"Bottom-face candidates ("<Z"): {len(bot_faces)}")
    except Exception as e:
        print(f"Face query debug failed: {e}")

    # --- Create several lightening cutouts in the mid-beam region ---
    # Keep-out from both X ends to avoid clevis + hook interfaces
    keepout = max(18.0, 0.23 * L)
    usable_min = xMin + keepout
    usable_max = xMax - keepout
    usable = max(0.0, usable_max - usable_min)

    # If the model is unexpectedly short, avoid cutting
    if usable < 10.0 or L <= 0 or W <= 0:
        print("Usable midspan too small for safe cutouts; returning original part.")
        return part

    # Slot sizing based on global width, with conservative ligaments
    side_lig = max(3.0, 0.18 * W)  # keep material to outer sides
    slot_w = 0.45 * W
    slot_w = min(slot_w, max(1.0, W - 2.0 * side_lig))
    slot_w = max(4.0, slot_w)

    # Slot length based on usable span; keep separation and avoid blending zones
    n = 3
    spacing = usable / (n + 1)
    slot_l = min(0.22 * L, 0.70 * spacing)
    slot_l = max(12.0, slot_l)

    # Centers equally spaced along usable span
    xs = [usable_min + spacing * (i + 1) for i in range(n)]

    print("=== Cutout plan ===")
    print(f"keepout={keepout:.3f}  usable=[{usable_min:.3f},{usable_max:.3f}]  usable={usable:.3f}")
    print(f"slot_w={slot_w:.3f}  slot_l={slot_l:.3f}  centers_x={['{:.3f}'.format(v) for v in xs]}")

    # Cut from the (largest) top face. Use ProjectedOrigin so the global origin projects into the sketch plane.
    # Slots are centered on y=0 (symmetry plane).
    try:
        pts = [(x, 0.0) for x in xs]
        result = (
            part
            .faces(">Z")
            .workplane(centerOption="ProjectedOrigin")
            .pushPoints(pts)
            .slot2D(slot_l, slot_w, angle=0)
            .cutThruAll()
        )
    except Exception as e:
        print("Cut operation failed; returning original part. Error:")
        import traceback
        traceback.print_exc()
        return part

    # (Optional fillets to be added in a later iteration once we can reliably select the new edges)
    return result
