def my_cad_function(args):
    import cadquery as cq
    import os

    # Target minimum clearance between handle and coffeepot
    base_clearance = 2.0  # mm

    input_file = os.path.expanduser(args.get('input_file', ''))
    wp = cq.importers.importStep(input_file)
    root = wp.val() if hasattr(wp, 'val') else wp
    if root is None:
        raise ValueError('Failed to import STEP (empty shape)')

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
        print('WARNING: <2 solids; nothing to edit.')
        return wp

    # --- Identify handle candidate(s) ---
    # U-handle/guard typically has: large X span (~254), thin Y span (~25-60), large Z span.
    handle_candidates = []
    for i, s in enumerate(solids):
        bb, vol = bbinfo(s)
        if bb.xlen > 220 and 8 < bb.ylen < 90 and bb.zlen > 140 and vol > 5e4:
            handle_candidates.append(i)

    # Fallback: pick solid with maximum X span but not the main housing (largest volume)
    if not handle_candidates:
        vols = [s.Volume() for s in solids]
        housing_idx = max(range(len(solids)), key=lambda k: vols[k])
        best = None
        for i, s in enumerate(solids):
            if i == housing_idx:
                continue
            bb, vol = bbinfo(s)
            score = bb.xlen
            # Prefer thin-ish Y to catch the bracket
            if 8 < bb.ylen < 90:
                score += 200
            if best is None or score > best[0]:
                best = (score, i)
        if best is not None:
            handle_candidates = [best[1]]

    print(f"Handle candidate indices: {handle_candidates}")
    if not handle_candidates:
        print('WARNING: Could not identify handle; returning original.')
        return wp

    # --- Find coffeepot as the solid that (a) intersects handle and (b) is not a duplicate handle piece ---
    def is_duplicate(a_idx, b_idx, inter_vol):
        a, b = solids[a_idx], solids[b_idx]
        bbA, volA = bbinfo(a)
        bbB, volB = bbinfo(b)
        # Very similar bbox and volume, and intersection is basically the smaller one => likely duplicate/overlap
        dims_close = (abs(bbA.xlen - bbB.xlen) < 0.5 and abs(bbA.ylen - bbB.ylen) < 0.5 and abs(bbA.zlen - bbB.zlen) < 0.5)
        vol_close = (abs(volA - volB) / max(1.0, min(volA, volB)) < 0.05)
        if dims_close and vol_close and inter_vol > 0.95 * min(volA, volB):
            return True
        return False

    # Exclude main housing from being considered a pot
    vols = [s.Volume() for s in solids]
    housing_idx = max(range(len(solids)), key=lambda k: vols[k])

    best_pair = None  # (inter_vol, handle_idx, pot_idx)
    for h_idx in handle_candidates:
        for j in range(len(solids)):
            if j == h_idx or j == housing_idx:
                continue
            try:
                inter = solids[h_idx].intersect(solids[j])
                inter_vol = inter.Volume() if inter is not None else 0.0
            except Exception as e:
                print(f"Intersect failed for pair (handle {h_idx}, solid {j}): {e}")
                inter_vol = 0.0
            if inter_vol <= 1e-3:
                continue

            # Skip obvious duplicate/overlapping parts
            if is_duplicate(h_idx, j, inter_vol):
                print(f"Skipping duplicate-like intersection (handle {h_idx}, solid {j}) inter_vol={inter_vol:.3f}")
                continue

            # Prefer a pot-like body: not super-thin in Y (avoid washers/plates)
            bbJ = solids[j].BoundingBox()
            pot_bonus = 0.0
            if bbJ.ylen > 30:
                pot_bonus += 1.0
            if bbJ.ylen > 60:
                pot_bonus += 1.0

            score = inter_vol * (1.0 + 0.15 * pot_bonus)
            print(f"Handle {h_idx} intersects Solid {j}: inter_vol={inter_vol:.3f}, score={score:.3f}")
            if best_pair is None or score > best_pair[0]:
                best_pair = (score, inter_vol, h_idx, j)

    if best_pair is None:
        print('No handle<->coffeepot intersection detected (within heuristic); returning original.')
        return wp

    _, inter_vol0, handle_idx, pot_idx = best_pair
    print(f"Selected (handle_idx={handle_idx}) vs (pot_idx={pot_idx}) initial_intersection_vol={inter_vol0:.3f} mm^3")

    handle = solids[handle_idx]
    pot = solids[pot_idx]

    # --- Utility: scale a shape about its bbox center ---
    def scaled_about_center(shape, scale_factor):
        bb = shape.BoundingBox()
        c = bb.center
        return shape.translate((-c.x, -c.y, -c.z)).scale(scale_factor).translate((c.x, c.y, c.z))

    # Compute a conservative radius for scaling conversion (half of max bbox length)
    pot_bb = pot.BoundingBox()
    r = 0.5 * max(pot_bb.xlen, pot_bb.ylen, pot_bb.zlen)
    if r <= 1e-6:
        print('WARNING: Pot bbox degenerate; returning original.')
        return wp

    # --- Apply progressive relief cut until intersection is gone (or attempts exhausted) ---
    handle_cut = handle
    cleared = False
    for attempt in range(5):
        clearance = base_clearance + 1.0 * attempt
        scale = 1.0 + (clearance / r)
        pot_tool = scaled_about_center(pot, scale)
        print(f"Attempt {attempt}: clearance={clearance:.2f}mm => scale={scale:.6f}")

        try:
            candidate = handle_cut.cut(pot_tool)
        except Exception as e:
            print(f"Cut failed on attempt {attempt}: {e}")
            raise

        # If cut returns a compound/multi-solid, keep the largest solid as the handle
        cand_solids = list(candidate.Solids()) if hasattr(candidate, 'Solids') else []
        if len(cand_solids) == 0:
            # fallback: keep candidate as-is
            handle_cut = candidate
        elif len(cand_solids) == 1:
            handle_cut = cand_solids[0]
        else:
            handle_cut = max(cand_solids, key=lambda s: s.Volume())
            print(f"Cut produced {len(cand_solids)} solids; keeping largest as handle.")

        # Re-check intersection
        try:
            inter2 = handle_cut.intersect(pot)
            inter2_vol = inter2.Volume() if inter2 is not None else 0.0
        except Exception as e:
            print(f"Post-check intersect failed: {e}")
            inter2_vol = 1e9

        print(f"Post-cut intersection vol (attempt {attempt}): {inter2_vol:.6f} mm^3")
        if inter2_vol <= 1e-3:
            cleared = True
            break

    if not cleared:
        print('WARNING: Could not fully clear collision within attempts; model updated with best-effort relief.')

    # --- Recombine solids (replace ONLY the selected handle solid) ---
    new_solids = []
    for k, s in enumerate(solids):
        new_solids.append(handle_cut if k == handle_idx else s)

    result = cq.Compound.makeCompound(new_solids)
    print('Applied handle relief cut against coffeepot keep-out and rebuilt compound.')
    print(f"Final status: collision_cleared={cleared}")
    return result
