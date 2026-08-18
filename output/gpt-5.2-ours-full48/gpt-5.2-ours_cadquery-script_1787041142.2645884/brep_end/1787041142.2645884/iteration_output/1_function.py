def my_cad_function(args):
    import cadquery as cq
    import os, math, traceback

    # --- Load input STEP ---
    input_file = args.get("input_file", None)
    if not input_file:
        raise ValueError("args['input_file'] is required")
    input_file = os.path.expanduser(input_file)
    if not os.path.exists(input_file):
        raise ValueError(f"Missing STEP file: {input_file}")

    part = cq.importers.importStep(input_file)
    shp = part.val()

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

    # Quick face query (debug only)
    try:
        top_faces = part.faces(">Z").vals()
        bot_faces = part.faces("<Z").vals()
        print(f"Top-face candidates (>Z): {len(top_faces)}")
        print(f"Bottom-face candidates (<Z): {len(bot_faces)}")
    except Exception as e:
        print(f"Face query debug failed: {e}")

    # --- Estimate mid-beam width more robustly than global W ---
    Wmid, Hmid = W, H
    try:
        mid_x = 0.5 * (xMin + xMax)
        # Intersect with a mid-span window to avoid the clevis/hook affecting width
        win_len = max(10.0, 0.35 * L)
        win = cq.Workplane("XY").box(win_len, 10.0 * W, 10.0 * H).translate((mid_x, 0, 0))
        mid = part.intersect(win)
        mid_bb = mid.val().BoundingBox()
        Wmid = mid_bb.ymax - mid_bb.ymin
        Hmid = mid_bb.zmax - mid_bb.zmin
        print("=== Mid-span window diagnostics ===")
        print(f"Mid-span Wmid={Wmid:.3f}  Hmid={Hmid:.3f}  (from intersect window)")
    except Exception as e:
        print(f"Mid-span width estimate failed; falling back to global bbox. Error: {e}")
        Wmid, Hmid = W, H

    # --- Plan several through-all obround lightening cutouts in S2 ---
    if L <= 0 or Wmid <= 0 or Hmid <= 0:
        print("Invalid bounding box; returning original part.")
        return part

    # Keep-out from ends to avoid clevis + hook interfaces
    keepout = max(18.0, 0.23 * L)
    usable_min = xMin + keepout
    usable_max = xMax - keepout
    usable = usable_max - usable_min

    if usable < 25.0:
        print("Usable midspan too small for safe cutouts; returning original part.")
        return part

    n = 3
    spacing = usable / (n + 1)

    # Conservative ligaments to side walls (avoid breaking into side planes)
    side_lig = max(3.0, 0.18 * Wmid)
    max_slot_w = max(0.0, Wmid - 2.0 * side_lig)
    slot_w = min(0.55 * Wmid, max_slot_w)
    slot_w = max(4.0, slot_w)

    # Slot length constrained by spacing and usable window
    end_margin = max(3.0, 0.12 * spacing)
    slot_l = min(0.75 * spacing, max(12.0, 0.18 * L))
    # ensure the slot fits between neighboring centers
    slot_l = min(slot_l, max(8.0, spacing - 2.0 * end_margin))

    if slot_w <= 4.0 or slot_l <= 8.0 or slot_w >= Wmid:
        print("Computed slot dimensions not feasible; returning original part.")
        print(f"slot_w={slot_w:.3f}, slot_l={slot_l:.3f}, Wmid={Wmid:.3f}")
        return part

    xs = [usable_min + spacing * (i + 1) for i in range(n)]

    print("=== Cutout plan ===")
    print(f"keepout={keepout:.3f}  usable=[{usable_min:.3f},{usable_max:.3f}]  usable={usable:.3f}")
    print(f"n={n}  spacing={spacing:.3f}")
    print(f"slot_w={slot_w:.3f}  slot_l={slot_l:.3f}")
    print(f"centers_x={[round(v,3) for v in xs]}")

    # Perform cuts on a global XY workplane so x/y coordinates map directly to the model axes.
    # This yields through-all Z cuts, centered on y=0, aligned with X.
    try:
        result = (
            part
            .workplane("XY")
            .pushPoints([(x, 0.0) for x in xs])
            .slot2D(slot_l, slot_w, angle=0)
            .cutThruAll()
        )
    except Exception:
        print("Cut operation failed; returning original part. Traceback:")
        traceback.print_exc()
        return part

    return result
