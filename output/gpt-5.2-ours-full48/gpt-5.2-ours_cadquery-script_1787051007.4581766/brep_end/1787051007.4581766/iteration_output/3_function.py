def my_cad_function(args):
    import cadquery as cq
    import os

    # --- Parameters ---
    clearance_gap = 2.0  # mm desired minimum separation
    safety = 0.2         # mm extra margin
    inter_vol_tol = 1e-2 # mm^3 intersection volume tolerance for 'collision'
    near_tol = 0.05      # mm treat as contact/near-collision

    input_file = os.path.expanduser(args.get("input_file", ""))

    # --- Load STEP ---
    wp = cq.importers.importStep(input_file)
    root = wp.val() if hasattr(wp, "val") else wp
    if root is None:
        raise ValueError("Failed to import STEP (empty shape)")

    solids = list(root.Solids())
    print(f"Loaded STEP: {input_file}")
    print(f"Root valid: {root.isValid()}")
    print(f"Solids found: {len(solids)}")

    if len(solids) < 2:
        print("<2 solids; nothing to edit.")
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

    # --- Identify housing (largest volume) ---
    vols = [float(s.Volume()) for s in solids]
    housing_idx = max(range(len(solids)), key=lambda k: vols[k])

    # --- Identify handle (U-bracket) candidate ---
    handle_candidates = []
    for i, s in enumerate(solids):
        if i == housing_idx:
            continue
        bb, vol = bbinfo(s)
        # Handle is a long X-span U frame with modest Y thickness and substantial Z span
        if bb.xlen > 220 and 8 < bb.ylen < 90 and bb.zlen > 140 and vol > 5e4:
            handle_candidates.append(i)

    # Fallback: choose best score non-housing
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
            score += min(vol / 1e5, 50)  # small volume preference without dominating
            if best is None or score > best[0]:
                best = (score, i)
        if best:
            handle_candidates = [best[1]]

    print(f"Handle candidate indices: {handle_candidates}")
    if not handle_candidates:
        print("WARNING: Could not identify handle; returning original.")
        return wp

    handle_idx = handle_candidates[0]
    handle = solids[handle_idx]

    # --- OCP tools ---
    try:
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
        from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    except Exception as e:
        raise ImportError(f"Required OCP modules unavailable: {e}")

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

    # --- Find actual colliding solids with handle (by intersection volume) ---
    collisions = []
    for j, s in enumerate(solids):
        if j in (housing_idx, handle_idx):
            continue
        vol = float(s.Volume())
        # Skip tiny hardware-ish solids for speed (but keep medium/large ones)
        if vol < 2e3:
            continue
        iv = common_volume(handle, s)
        if iv > inter_vol_tol:
            collisions.append((iv, j))

    collisions.sort(reverse=True, key=lambda t: t[0])
    print("Handle collision candidates (intersection volume mm^3):")
    for iv, j in collisions[:10]:
        bb, v = bbinfo(solids[j])
        print(f"  idx={j}  interVol={iv:.3f}  vol={v:.1f}  bb=({bb.xlen:.1f},{bb.ylen:.1f},{bb.zlen:.1f})")

    # If nothing intersects, look for too-close solids (min distance)
    pot_tool_parts = []
    if collisions:
        pot_tool_parts = [solids[j] for _, j in collisions]
        print(f"Detected {len(pot_tool_parts)} intersecting solid(s) with handle.")
    else:
        # Find nearest substantial solid in handle Y band
        handle_bb = handle.BoundingBox()

        def overlap_len(a0, a1, b0, b1):
            return max(0.0, min(a1, b1) - max(a0, b0))

        best = None  # (dist, -vol, idx)
        for j, s in enumerate(solids):
            if j in (housing_idx, handle_idx):
                continue
            bb, vol = bbinfo(s)
            if vol < 2e4:
                continue
            # must overlap in Y with handle span somewhat
            if overlap_len(handle_bb.ymin, handle_bb.ymax, bb.ymin, bb.ymax) < 1.0:
                continue
            d = min_dist(handle, s)
            key = (d, -vol, j)
            if best is None or key < best:
                best = key

        if best is None:
            print("WARNING: No nearby coffeepot candidate found; returning original.")
            return wp

        d, negv, pot_idx = best
        print(f"No intersection detected. Nearest candidate idx={pot_idx} dist={d:.6f}mm")
        if d >= clearance_gap:
            print(f"Clearance already >= {clearance_gap}mm and no intersection; no modification applied.")
            return wp
        pot_tool_parts = [solids[pot_idx]]

    # Build tool body (compound of all colliding parts)
    tool_body = cq.Compound.makeCompound(pot_tool_parts)

    # --- Create keep-out tool (offset outward) ---
    needed = clearance_gap + safety
    keepout = None

    try:
        from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffsetShape
        mk = BRepOffsetAPI_MakeOffsetShape(tool_body.wrapped, float(needed), 1.0e-3)
        mk.Perform()
        keepout = cq.Shape(mk.Shape())
        print(f"Created keep-out by 3D offset: {needed:.3f}mm")
    except Exception as e:
        print(f"Offset keep-out failed; falling back to scaling. Reason: {e}")

    if keepout is None:
        bb = tool_body.BoundingBox()
        c = bb.center
        r = 0.5 * max(bb.xlen, bb.ylen, bb.zlen)
        if r < 1e-6:
            print("WARNING: Tool bbox degenerate; returning original.")
            return wp
        scale = 1.0 + (needed / r)
        keepout = tool_body.translate((-c.x, -c.y, -c.z)).scale(scale).translate((c.x, c.y, c.z))
        print(f"Created keep-out by scaling: scale={scale:.6f} (approx)")

    # --- Cut handle with keep-out ---
    # (This is the most robust way to guarantee clearance without needing face IDs)
    try:
        handle_cut_raw = handle.cut(keepout)
    except Exception as e:
        raise RuntimeError(f"Handle cut failed: {e}")

    # Keep largest resulting solid as handle
    cand = list(handle_cut_raw.Solids()) if hasattr(handle_cut_raw, "Solids") else []
    if not cand:
        handle_cut = handle_cut_raw
    else:
        handle_cut = max(cand, key=lambda s: float(s.Volume()))
        if len(cand) > 1:
            print(f"Cut produced {len(cand)} solids; keeping largest as handle.")

    # --- Validate: no intersection + min clearance ---
    post_iv = common_volume(handle_cut, tool_body)
    post_d = min_dist(handle_cut, tool_body)
    print(f"Post-edit intersection volume(handle, coffeepot_tool) = {post_iv:.6f} mm^3")
    print(f"Post-edit min distance(handle, coffeepot_tool) = {post_d:.6f} mm")

    if post_iv > inter_vol_tol:
        print("WARNING: Still intersecting after cut; consider increasing safety or using larger tool set.")
    if post_d < (clearance_gap - 1e-3):
        print("WARNING: Clearance still below target after cut; consider larger offset.")

    # --- Rebuild compound with updated handle ---
    new_solids = []
    for k, s in enumerate(solids):
        new_solids.append(handle_cut if k == handle_idx else s)

    result = cq.Compound.makeCompound(new_solids)
    print("Updated handle to remove collision / enforce clearance.")
    return result
