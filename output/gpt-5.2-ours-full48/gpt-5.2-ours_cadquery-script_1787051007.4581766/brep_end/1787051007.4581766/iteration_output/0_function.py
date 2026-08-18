def my_cad_function(args):
    import cadquery as cq
    import os

    clearance = 2.0  # mm target keep-out gap

    input_file = os.path.expanduser(args.get('input_file', ''))
    shape_wp = cq.importers.importStep(input_file)
    root = shape_wp.val() if hasattr(shape_wp, 'val') else shape_wp

    if not root:
        raise ValueError('Failed to import STEP (empty shape)')

    # --- Extract solids ---
    solids = list(root.Solids())
    print(f"Loaded STEP: {input_file}")
    print(f"Root valid: {root.isValid()}")
    print(f"Solids found: {len(solids)}")

    if len(solids) < 2:
        print("WARNING: Only one solid found; cannot detect handle<->coffeepot collision. Returning original model.")
        return shape_wp

    # Print basic solid diagnostics
    for i, s in enumerate(solids):
        bb = s.BoundingBox()
        print(
            f"Solid[{i}]: vol={s.Volume():.3f} mm^3, "
            f"bbox=({bb.xlen:.2f},{bb.ylen:.2f},{bb.zlen:.2f}), "
            f"center=({bb.center.x:.2f},{bb.center.y:.2f},{bb.center.z:.2f})"
        )

    # --- Find the most-interfering pair (likely handle vs coffeepot) ---
    best = None  # (vol, i, j, inter_shape)
    for i in range(len(solids)):
        for j in range(i + 1, len(solids)):
            try:
                inter = solids[i].intersect(solids[j])
                v = inter.Volume() if inter is not None else 0.0
            except Exception as e:
                print(f"Intersect failed for pair ({i},{j}): {e}")
                v = 0.0
                inter = None
            if v and v > 1e-3:
                print(f"Intersection pair ({i},{j}) volume: {v:.3f} mm^3")
            if best is None or v > best[0]:
                best = (v, i, j, inter)

    if best is None or best[0] <= 1e-3:
        print("No meaningful intersections detected between any solids; returning original model.")
        return shape_wp

    _, i, j, _ = best
    sA, sB = solids[i], solids[j]
    bbA, bbB = sA.BoundingBox(), sB.BoundingBox()

    # Heuristic: handle/guard typically has larger X-span than coffeepot-like body.
    # (If wrong, user can refine after we see the render.)
    if bbA.xlen >= bbB.xlen:
        handle_idx, pot_idx = i, j
    else:
        handle_idx, pot_idx = j, i

    handle = solids[handle_idx]
    pot = solids[pot_idx]
    print(f"Selected handle_idx={handle_idx}, pot_idx={pot_idx} (heuristic by bbox.xlen)")

    # --- Build a keep-out tool from coffeepot (expanded slightly for clearance) ---
    pot_bb = pot.BoundingBox()
    pot_center = pot_bb.center
    r = 0.5 * max(pot_bb.xlen, pot_bb.ylen, pot_bb.zlen)
    if r <= 1e-6:
        print("WARNING: Pot bbox degenerate; returning original model.")
        return shape_wp

    scale = 1.0 + (clearance / r)
    print(f"Pot keep-out: r~{r:.2f} -> scale={scale:.6f} for clearance={clearance}mm")

    # Scale about pot center (translate->scale->translate back)
    pot_tool = pot.translate((-pot_center.x, -pot_center.y, -pot_center.z)).scale(scale).translate((pot_center.x, pot_center.y, pot_center.z))

    # --- Cut the handle by the expanded coffeepot to remove collision ---
    try:
        handle_cut = handle.cut(pot_tool)
    except Exception as e:
        print(f"Handle cut failed: {e}")
        raise

    # --- Recombine solids (replace handle with modified one) ---
    new_solids = []
    for k, s in enumerate(solids):
        new_solids.append(handle_cut if k == handle_idx else s)

    result = cq.Compound.makeCompound(new_solids)
    print("Collision-relief cut applied to selected handle solid.")
    return result
