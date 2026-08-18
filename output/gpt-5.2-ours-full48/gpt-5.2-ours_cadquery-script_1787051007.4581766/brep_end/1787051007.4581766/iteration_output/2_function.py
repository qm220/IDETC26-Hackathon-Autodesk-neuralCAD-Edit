def my_cad_function(args):
    import cadquery as cq
    import os
    import math

    # Desired minimum clearance between handle and coffeepot
    clearance_gap = 2.0  # mm
    safety = 0.2         # mm extra

    # --- Load STEP ---
    input_file = os.path.expanduser(args.get("input_file", ""))
    wp = cq.importers.importStep(input_file)
    root = wp.val() if hasattr(wp, "val") else wp
    if root is None:
        raise ValueError("Failed to import STEP (empty shape)")

    solids = list(root.Solids())
    print(f"Loaded STEP: {input_file}")
    print(f"Root valid: {root.isValid()}")
    print(f"Solids found: {len(solids)}")

    def bbinfo(s):
        bb = s.BoundingBox()
        return bb, s.Volume()

    for i, s in enumerate(solids):
        bb, vol = bbinfo(s)
        print(
            f"Solid[{i}]: vol={vol:.3f} mm^3, "
            f"bbox=({bb.xlen:.2f},{bb.ylen:.2f},{bb.zlen:.2f}), "
            f"center=({bb.center.x:.2f},{bb.center.y:.2f},{bb.center.z:.2f})"
        )

    if len(solids) < 2:
        print("WARNING: <2 solids; nothing to edit.")
        return wp

    # --- Identify handle (U-bracket) candidate ---
    handle_candidates = []
    for i, s in enumerate(solids):
        bb, vol = bbinfo(s)
        if bb.xlen > 220 and 8 < bb.ylen < 90 and bb.zlen > 140 and vol > 5e4:
            handle_candidates.append(i)

    # Fallback: choose non-housing solid with largest X span + thin-ish Y
    vols = [s.Volume() for s in solids]
    housing_idx = max(range(len(solids)), key=lambda k: vols[k])
    if not handle_candidates:
        best = None
        for i, s in enumerate(solids):
            if i == housing_idx:
                continue
            bb, vol = bbinfo(s)
            score = bb.xlen
            if 8 < bb.ylen < 90:
                score += 200
            if bb.zlen > 140:
                score += 50
            if best is None or score > best[0]:
                best = (score, i)
        if best is not None:
            handle_candidates = [best[1]]

    print(f"Handle candidate indices: {handle_candidates}")
    if not handle_candidates:
        print("WARNING: Could not identify handle; returning original.")
        return wp

    handle_idx = handle_candidates[0]
    handle = solids[handle_idx]
    handle_bb = handle.BoundingBox()

    # --- Distance-based collision/clearance detection (handles touch / zero-volume interference) ---
    try:
        from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    except Exception as e:
        raise ImportError(f"OCP.BRepExtrema unavailable; cannot compute clearances: {e}")

    def min_dist(a, b):
        dss = BRepExtrema_DistShapeShape(a.wrapped, b.wrapped)
        dss.Perform()
        if not dss.IsDone():
            return None
        return float(dss.Value())

    def overlap_len(a0, a1, b0, b1):
        return max(0.0, min(a1, b1) - max(a0, b0))

    # Find the most likely coffeepot as the closest substantial solid to the handle
    best = None  # (dist, -vol, idx)
    for j, s in enumerate(solids):
        if j in (handle_idx, housing_idx):
            continue
        bb, vol = bbinfo(s)

        # Filter tiny hardware-ish solids
        if vol < 2e4:
            continue
        if bb.ylen < 20 and bb.zlen < 30:
            continue

        # Must be in roughly the same Y band as the handle (helps ignore the power cord/plug)
        y_ov = overlap_len(handle_bb.ymin, handle_bb.ymax, bb.ymin, bb.ymax)
        if y_ov < 1.0:
            continue

        d = min_dist(handle, s)
        if d is None:
            continue

        # Prefer closer, and for ties prefer larger volume
        key = (d, -vol, j)
        if best is None or key < best:
            best = key

    if best is None:
        print("WARNING: Could not find a coffeepot candidate near the handle; returning original.")
        return wp

    pot_dist, neg_vol, pot_idx = best
    pot = solids[pot_idx]
    pot_bb = pot.BoundingBox()

    print(f"Selected coffeepot candidate idx={pot_idx}, min_dist_to_handle={pot_dist:.6f} mm")

    # If already has required clearance, no change
    if pot_dist >= clearance_gap:
        print(f"Clearance already >= {clearance_gap}mm; no modification applied.")
        return wp

    # Amount we need to relieve on the handle side
    needed = (clearance_gap - pot_dist) + safety
    print(f"Clearance shortfall: need ~{needed:.3f} mm additional gap (including safety).")

    # --- Build a keep-out tool from the coffeepot, expanded outward by 'needed' ---
    tool = None

    # Preferred: true 3D offset (more accurate than scaling)
    try:
        from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffsetShape
        mk = BRepOffsetAPI_MakeOffsetShape(pot.wrapped, float(needed), 1.0e-3)
        mk.Perform()
        tool = cq.Shape(mk.Shape())
        print("Created keep-out tool using BRepOffsetAPI_MakeOffsetShape.")
    except Exception as e:
        print(f"Offset keep-out failed; falling back to scaled keep-out. Reason: {e}")

    # Fallback: isotropic scale about bbox center (approximate)
    if tool is None:
        c = pot_bb.center
        r = 0.5 * max(pot_bb.xlen, pot_bb.ylen, pot_bb.zlen)
        if r < 1e-6:
            print("WARNING: Pot bbox degenerate; returning original.")
            return wp
        scale = 1.0 + (needed / r)
        tool = pot.translate((-c.x, -c.y, -c.z)).scale(scale).translate((c.x, c.y, c.z))
        print(f"Created keep-out tool by scaling about center. scale={scale:.6f}")

    # Limit the cut to the central region to avoid damaging side fastener interfaces
    # (the cheeks/fasteners are near the extreme +/-X ends of the handle)
    x_half = 0.33 * handle_bb.xlen  # keep only middle third-ish
    y_pad = 10.0
    z_pad = 15.0
    region = cq.Workplane("XY").box(
        2.0 * x_half,
        (handle_bb.ylen + 2.0 * y_pad),
        (max(handle_bb.zlen, pot_bb.zlen) + 2.0 * z_pad),
        centered=(True, True, True),
    ).translate((handle_bb.center.x, handle_bb.center.y, handle_bb.center.z))

    tool_limited = tool.intersect(region.val())

    # --- Apply relief cut on handle ---
    try:
        cut_candidate = handle.cut(tool_limited)
    except Exception as e:
        print(f"Handle cut failed: {e}")
        raise

    # If multiple solids result, keep the largest
    cand_solids = list(cut_candidate.Solids()) if hasattr(cut_candidate, "Solids") else []
    if len(cand_solids) == 0:
        handle_cut = cut_candidate
    elif len(cand_solids) == 1:
        handle_cut = cand_solids[0]
    else:
        handle_cut = max(cand_solids, key=lambda s: s.Volume())
        print(f"Cut produced {len(cand_solids)} solids; keeping largest as handle.")

    # Validate new clearance
    new_dist = min_dist(handle_cut, pot)
    print(f"Post-edit min_dist(handle, coffeepot) = {new_dist:.6f} mm")

    # --- Rebuild compound with updated handle only ---
    new_solids = []
    for k, s in enumerate(solids):
        new_solids.append(handle_cut if k == handle_idx else s)

    result = cq.Compound.makeCompound(new_solids)
    print("Applied handle relief cut (distance-based) and rebuilt compound.")
    print(f"Target clearance={clearance_gap}mm, achieved={new_dist:.6f}mm")
    return result
