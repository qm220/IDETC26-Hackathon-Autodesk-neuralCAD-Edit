def my_cad_function(args):
    import cadquery as cq
    import os
    
    input_file = os.path.expanduser(args.get('input_file', ''))
    shape_wp = cq.importers.importStep(input_file)
    shape = shape_wp.val() if hasattr(shape_wp, 'val') else shape_wp

    solids = list(shape.Solids())
    print(f"Loaded STEP: {input_file}")
    print(f"Total solids: {len(solids)}")

    overall_bb = shape.BoundingBox()
    midX = overall_bb.center.x
    print(f"Overall bbox: xlen={overall_bb.xlen:.3f}, ylen={overall_bb.ylen:.3f}, zlen={overall_bb.zlen:.3f}")
    print(f"Overall center: ({overall_bb.center.x:.3f}, {overall_bb.center.y:.3f}, {overall_bb.center.z:.3f})")

    # --- Heuristic identification of the existing stand/handle ---
    # Expectation: stand is a relatively small solid located mainly on one side (x significantly offset from mid-plane).
    # We will (a) print debug, (b) pick one candidate, (c) mirror it about x=midX, (d) flatten bottoms of both.
    x_half = overall_bb.xlen / 2.0

    per = []
    for i, s in enumerate(solids):
        bb = s.BoundingBox()
        vol = s.Volume()
        per.append((i, vol, bb))
        print(
            f"Solid[{i}]: V={vol:.3f}  center=({bb.center.x:.3f},{bb.center.y:.3f},{bb.center.z:.3f})  "
            f"dims=({bb.xlen:.3f},{bb.ylen:.3f},{bb.zlen:.3f})  "
            f"xmin={bb.xmin:.3f} xmax={bb.xmax:.3f} zmin={bb.zmin:.3f} zmax={bb.zmax:.3f}"
        )

    # Candidate scoring
    candidates = []
    for i, vol, bb in per:
        x_off = abs(bb.center.x - midX)
        # Prefer solids that are offset in X, not too huge in X span, and not super long in Z (cord is very long in Z).
        score = 0.0
        score += (x_off / max(1e-6, x_half)) * 2.0
        if bb.xlen < overall_bb.xlen * 0.75:
            score += 1.0
        if bb.zlen < overall_bb.zlen * 0.60:
            score += 1.0
        if vol < (sum(v for _, v, _ in per) / max(1, len(per))) * 1.5:
            score += 0.5
        candidates.append((score, i, vol, bb, x_off))

    candidates.sort(reverse=True, key=lambda t: t[0])
    print("--- Candidate stand/handle solids (top 8) ---")
    for rank, (score, i, vol, bb, x_off) in enumerate(candidates[:8]):
        print(
            f"rank {rank}: Solid[{i}] score={score:.3f} x_off={x_off:.3f} V={vol:.3f} "
            f"center=({bb.center.x:.3f},{bb.center.y:.3f},{bb.center.z:.3f}) dims=({bb.xlen:.3f},{bb.ylen:.3f},{bb.zlen:.3f})"
        )

    # Pick best candidate as the existing stand/handle
    stand_idx = candidates[0][1] if candidates else None

    # --- Heuristic identification of cordholder ---
    # Assume cordholder is a small protrusion near the bottom (zmin close to overall zmin) and relatively small volume.
    # We will *only* remove if it looks clearly like a tiny block; otherwise keep for now.
    total_vol = sum(v for _, v, _ in per)
    cordholder_idxs = []
    for i, vol, bb in per:
        if vol < total_vol * 0.002 and (bb.zmin - overall_bb.zmin) < 0.15 * max(1e-6, overall_bb.zlen):
            # also avoid removing very long thin items like cord: require modest zlen
            if bb.zlen < overall_bb.zlen * 0.25:
                cordholder_idxs.append(i)

    print(f"Heuristic cordholder candidates to remove: {cordholder_idxs}")

    # If no stand found, return original for inspection
    if stand_idx is None:
        print("No stand/handle candidate found; returning original shape.")
        return shape_wp

    stand_solid = solids[stand_idx]
    stand_bb = stand_solid.BoundingBox()

    # --- Flatten bottom of stand by cutting below z_cut ---
    # Choose a cut plane slightly above the lowest point of the existing stand.
    z_cut = stand_bb.zmin + 1.5  # mm; adjust after viewing
    print(f"Stand idx={stand_idx}, stand zmin={stand_bb.zmin:.3f} => z_cut={z_cut:.3f}")

    # Big cutting box whose TOP face is at z_cut, removing material below.
    cut_box = cq.Workplane("XY").box(20000, 20000, 20000, centered=(True, True, True)).translate((0, 0, z_cut - 10000))

    stand_flat = cq.Workplane().newObject([stand_solid]).cut(cut_box).val()

    # Mirror the flattened stand about x=midX
    stand_local = stand_flat.translate((-midX, 0, 0))
    stand_mir = cq.Workplane().newObject([stand_local]).mirror(mirrorPlane="YZ")
    stand_mir_solid = stand_mir.val().translate((midX, 0, 0))

    # --- Rebuild solids list: remove old stand, optionally remove cordholder, add stand_flat and stand_mir ---
    new_solids = []
    for i, s in enumerate(solids):
        if i == stand_idx:
            continue
        if i in cordholder_idxs:
            continue
        new_solids.append(s)

    new_solids.append(stand_flat)
    new_solids.append(stand_mir_solid)

    print(f"Solids after edit: {len(new_solids)} (removed stand idx {stand_idx}, removed {len(cordholder_idxs)} cordholder candidates, added 2 stands)")

    # Return as a compound (do not force-fuse all solids)
    result = cq.Compound.makeCompound(new_solids)
    return result
