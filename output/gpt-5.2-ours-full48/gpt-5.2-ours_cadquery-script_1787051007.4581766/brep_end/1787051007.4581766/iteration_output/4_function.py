def my_cad_function(args):
    import cadquery as cq
    import os

    # Goal:
    # Remove collision between handle (U-bracket) and coffeepot.
    # The previous iteration found no static intersection; collision is likely along an insertion/removal path.
    # Strategy: identify a 'coffeepot' candidate solid, create a swept keep-out volume by translating it along -Z,
    # offset keep-out by required clearance, and boolean-cut the handle with that keep-out.

    clearance_gap = 2.0   # mm
    safety = 0.3          # mm
    needed = clearance_gap + safety

    # Sweep assumptions (tunable): coffeepot is removed toward cable side (negative Z)
    sweep_total_z = 140.0   # mm travel envelope
    sweep_step_z = 20.0     # mm discretization for sweep envelope

    inter_vol_tol = 1e-2

    input_file = os.path.expanduser(args.get("input_file", ""))

    wp = cq.importers.importStep(input_file)
    root = wp.val() if hasattr(wp, "val") else wp
    if root is None:
        raise ValueError("Failed to import STEP (empty shape)")

    solids = list(root.Solids())
    print(f"Loaded STEP: {input_file}")
    print(f"Root valid: {root.isValid()}")
    print(f"Solids found: {len(solids)}")
    if len(solids) < 2:
        return wp

    def bbinfo(s):
        bb = s.BoundingBox()
        return bb, float(s.Volume())

    for i, s in enumerate(solids):
        bb, vol = bbinfo(s)
        print(
            f"Solid[{i}]: vol={vol:.3f} mm^3, "
            f"bbox=({bb.xlen:.2f},{bb.ylen:.2f},{bb.zlen:.2f}), "
            f"center=({bb.center.x:.2f},{bb.center.y:.2f},{bb.center.z:.2f})"
        )

    # Identify housing as largest volume
    vols = [float(s.Volume()) for s in solids]
    housing_idx = max(range(len(solids)), key=lambda k: vols[k])
    housing = solids[housing_idx]

    # Identify handle candidate (same heuristic as before)
    handle_candidates = []
    for i, s in enumerate(solids):
        if i == housing_idx:
            continue
        bb, vol = bbinfo(s)
        if bb.xlen > 220 and 8 < bb.ylen < 90 and bb.zlen > 140 and vol > 5e4:
            handle_candidates.append(i)

    if not handle_candidates:
        # fallback: best scoring non-housing
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
            score += min(vol / 1e5, 50)
            if best is None or score > best[0]:
                best = (score, i)
        if best:
            handle_candidates = [best[1]]

    print(f"Handle candidate indices: {handle_candidates}")
    if not handle_candidates:
        print("ERROR: Could not identify handle solid.")
        return wp

    handle_idx = handle_candidates[0]
    handle = solids[handle_idx]
    handle_bb = handle.BoundingBox()

    # OCP tools
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape

    def common_volume(a: cq.Shape, b: cq.Shape) -> float:
        com = BRepAlgoAPI_Common(a.wrapped, b.wrapped)
        com.Build()
        if not com.IsDone():
            return 0.0
        shp = cq.Shape(com.Shape())
        try:
            return float(shp.Volume())
        except Exception:
            return 0.0

    def min_dist(a: cq.Shape, b: cq.Shape) -> float:
        dss = BRepExtrema_DistShapeShape(a.wrapped, b.wrapped)
        dss.Perform()
        if not dss.IsDone():
            return float("inf")
        return float(dss.Value())

    # Identify coffeepot candidate:
    # Prefer a substantial solid located near/within the handle Y-span and near X center.
    coffeepot_cands = []
    for i, s in enumerate(solids):
        if i in (housing_idx, handle_idx):
            continue
        bb, vol = bbinfo(s)
        if vol < 3e4:
            continue
        # Must overlap handle in Y somewhat
        y_overlap = max(0.0, min(handle_bb.ymax, bb.ymax) - max(handle_bb.ymin, bb.ymin))
        if y_overlap < 10.0:
            continue
        # Roughly pot-like / internal module sized
        if bb.xlen < 70 or bb.zlen < 70 or bb.ylen < 60:
            continue
        # Prefer near centerline in X
        xcenter = abs(bb.center.x)
        score = vol - 5000.0 * xcenter
        # Prefer being in front half (toward negative Z where cable seems to run)
        score += 2000.0 * (-bb.center.z)
        coffeepot_cands.append((score, i))

    coffeepot_cands.sort(reverse=True, key=lambda t: t[0])
    print("Coffeepot candidate indices (ranked):", [i for _, i in coffeepot_cands[:8]])

    if not coffeepot_cands:
        print("ERROR: Could not identify coffeepot solid; model may not contain coffeepot geometry.")
        return wp

    pot_idx = coffeepot_cands[0][1]
    coffeepot = solids[pot_idx]
    pot_bb = coffeepot.BoundingBox()
    print(f"Selected coffeepot idx={pot_idx} center=({pot_bb.center.x:.2f},{pot_bb.center.y:.2f},{pot_bb.center.z:.2f}) bb=({pot_bb.xlen:.1f},{pot_bb.ylen:.1f},{pot_bb.zlen:.1f})")

    # Check current static relationship (for debug)
    iv0 = common_volume(handle, coffeepot)
    d0 = min_dist(handle, coffeepot)
    print(f"Static handle/pot: interVol={iv0:.6f} mm^3, minDist={d0:.6f} mm")

    # Build a swept envelope by translating the coffeepot along -Z
    # (discrete union of copies)
    copies = []
    n_steps = max(1, int(round(sweep_total_z / sweep_step_z)))
    for k in range(n_steps + 1):
        dz = -float(k) * float(sweep_step_z)
        copies.append(coffeepot.translate((0, 0, dz)))

    sweep_tool = cq.Compound.makeCompound(copies)
    print(f"Built sweep envelope: steps={n_steps+1}, total_z={sweep_total_z}mm, step={sweep_step_z}mm")

    # Offset keep-out outward to enforce clearance
    keepout = None
    try:
        from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffsetShape
        mk = BRepOffsetAPI_MakeOffsetShape(sweep_tool.wrapped, float(needed), 1.0e-3)
        mk.Perform()
        keepout = cq.Shape(mk.Shape())
        print(f"Created keep-out by 3D offset: {needed:.3f}mm")
    except Exception as e:
        print(f"WARNING: 3D offset failed; using non-offset sweep tool. Reason: {e}")
        keepout = sweep_tool

    # Cut handle with keep-out
    try:
        handle_cut_raw = handle.cut(keepout)
    except Exception as e:
        raise RuntimeError(f"Handle cut failed: {e}")

    # Keep largest resulting solid as handle
    cand = list(handle_cut_raw.Solids()) if hasattr(handle_cut_raw, "Solids") else []
    if cand:
        handle_cut = max(cand, key=lambda s: float(s.Volume()))
        if len(cand) > 1:
            print(f"Cut produced {len(cand)} solids; keeping largest as handle.")
    else:
        handle_cut = handle_cut_raw

    # Validation: sample along sweep to ensure no intersection and measure min distance
    worst_iv = 0.0
    worst_d = float("inf")
    for k in (0, int(n_steps/2), n_steps):
        dz = -float(k) * float(sweep_step_z)
        pot_k = coffeepot.translate((0, 0, dz))
        iv = common_volume(handle_cut, pot_k)
        d = min_dist(handle_cut, pot_k)
        worst_iv = max(worst_iv, iv)
        worst_d = min(worst_d, d)
        print(f"Sample k={k} dz={dz:.1f}: interVol={iv:.6f} minDist={d:.6f}")

    if worst_iv > inter_vol_tol:
        print("WARNING: Still intersecting for some sampled sweep positions; consider increasing sweep_total_z or needed.")
    if keepout is sweep_tool:
        print("WARNING: Offset keepout failed; clearance may be < target even if collision removed.")
    else:
        if worst_d < (clearance_gap - 1e-3):
            print("WARNING: Clearance below target at some sampled sweep positions; consider larger needed or finer sweep.")

    # Rebuild compound with updated handle
    new_solids = []
    for i, s in enumerate(solids):
        new_solids.append(handle_cut if i == handle_idx else s)

    result = cq.Compound.makeCompound(new_solids)
    print("Updated handle using swept keep-out to remove potential collision along removal path.")
    return result
