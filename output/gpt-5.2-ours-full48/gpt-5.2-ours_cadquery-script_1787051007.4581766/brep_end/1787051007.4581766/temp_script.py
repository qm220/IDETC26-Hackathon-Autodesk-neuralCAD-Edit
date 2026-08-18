def my_cad_function(args):
    import cadquery as cq
    import os

    # Goal: remove collision between handle (U-bracket) and coffeepot.
    # This iteration improves robustness by:
    # 1) Better coffeepot identification
    # 2) Checking interference not only in the static pose, but along a plausible insertion/removal sweep
    # 3) If collision/insufficient clearance is found along the sweep, apply a localized relief cut on the handle

    clearance_gap = 2.0  # mm
    safety = 0.3
    dilate_r = clearance_gap + safety

    travel = 180.0   # mm sweep travel to test
    step = 10.0      # mm step for sweep sampling

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
        return root

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

    vols = [float(s.Volume()) for s in solids]
    housing_idx = max(range(len(solids)), key=lambda k: vols[k])

    # --- Identify handle solid ---
    handle_candidates = []
    for i, s in enumerate(solids):
        if i == housing_idx:
            continue
        bb, vol = bbinfo(s)
        # U-bracket: very wide in X, significant in Z, thin in Y
        if bb.xlen > 220 and bb.zlen > 140 and 8 < bb.ylen < 90 and vol > 5e4:
            handle_candidates.append(i)

    if not handle_candidates:
        # fallback scoring
        best = None
        for i, s in enumerate(solids):
            if i == housing_idx:
                continue
            bb, vol = bbinfo(s)
            score = 0.0
            score += 2.0 * bb.xlen
            score += 1.2 * bb.zlen
            score += 0.5 * bb.ylen
            if 8 < bb.ylen < 90:
                score += 300.0
            score += min(vol / 1e4, 250.0)
            if best is None or score > best[0]:
                best = (score, i)
        if best:
            handle_candidates = [best[1]]

    print(f"Handle candidate indices: {handle_candidates}")
    if not handle_candidates:
        raise RuntimeError("Could not identify handle solid")

    handle_idx = handle_candidates[0]
    handle = solids[handle_idx]

    # --- Identify coffeepot solid ---
    # Prefer a large, pot-like body: moderate X, large Y and Z compared to small features
    pot_candidates = []
    for i, s in enumerate(solids):
        if i in (housing_idx, handle_idx):
            continue
        bb, vol = bbinfo(s)
        # exclude tiny hardware/feet/cord bits
        if vol < 5e4:
            continue
        # coffeepot-ish: substantial Y and Z, not ultra-wide X like handle
        if bb.ylen > 70 and bb.zlen > 70 and bb.xlen < 220:
            # score: big volume, big Y/Z, near center X
            score = 0.002 * vol + 2.0 * bb.ylen + 2.0 * bb.zlen - 1.0 * abs(bb.center.x)
            pot_candidates.append((score, i))

    pot_candidates.sort(reverse=True, key=lambda t: t[0])
    pot_idx = pot_candidates[0][1] if pot_candidates else None

    if pot_idx is None:
        # fallback: nearest substantial solid to handle
        from OCP.BRepExtrema import BRepExtrema_DistShapeShape

        def min_dist(a: cq.Shape, b: cq.Shape) -> float:
            dss = BRepExtrema_DistShapeShape(a.wrapped, b.wrapped)
            dss.Perform()
            return float(dss.Value()) if dss.IsDone() else float("inf")

        near = []
        for i, s in enumerate(solids):
            if i in (housing_idx, handle_idx):
                continue
            bb, vol = bbinfo(s)
            if vol < 3e4:
                continue
            near.append((min_dist(handle, s), i))
        near.sort(key=lambda t: t[0])
        if not near:
            print("No coffeepot candidate found; leaving model unchanged.")
            return root
        pot_idx = near[0][1]

    coffeepot = solids[pot_idx]
    pot_bb = coffeepot.BoundingBox()
    print(
        f"Selected coffeepot idx={pot_idx} "
        f"center=({pot_bb.center.x:.2f},{pot_bb.center.y:.2f},{pot_bb.center.z:.2f}) "
        f"bb=({pot_bb.xlen:.1f},{pot_bb.ylen:.1f},{pot_bb.zlen:.1f})"
    )

    # --- OCP helpers: intersection volume + closest points ---
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

    def dist_and_points(a: cq.Shape, b: cq.Shape):
        dss = BRepExtrema_DistShapeShape(a.wrapped, b.wrapped)
        dss.Perform()
        if not dss.IsDone():
            return float("inf"), None, None
        d = float(dss.Value())
        try:
            p1 = dss.PointOnShape1(1)
            p2 = dss.PointOnShape2(1)
            pt1 = (float(p1.X()), float(p1.Y()), float(p1.Z()))
            pt2 = (float(p2.X()), float(p2.Y()), float(p2.Z()))
        except Exception:
            pt1, pt2 = None, None
        return d, pt1, pt2

    iv0 = common_volume(handle, coffeepot)
    d0, pH0, pP0 = dist_and_points(handle, coffeepot)
    print(f"Static: interVol={iv0:.6f} mm^3, minDist={d0:.6f} mm")

    # --- Sweep test: detect collision/low clearance along a plausible insertion direction ---
    axes = [("X", (1, 0, 0)), ("Y", (0, 1, 0)), ("Z", (0, 0, 1))]
    directions = []
    for ax, v in axes:
        for sgn in (-1.0, 1.0):
            directions.append((ax, sgn, v))

    best_dir = None
    best_metric = None  # (has_collision(0/1), maxCommonVol, minDist)
    dir_reports = []

    ts = [i * step for i in range(int(travel / step) + 1)]

    for ax, sgn, v in directions:
        max_cv = 0.0
        min_d = float("inf")
        for t in ts:
            dx = sgn * t * v[0]
            dy = sgn * t * v[1]
            dz = sgn * t * v[2]
            pot_t = coffeepot.translate((dx, dy, dz))
            cv = common_volume(handle, pot_t)
            d, _, _ = dist_and_points(handle, pot_t)
            if cv > max_cv:
                max_cv = cv
            if d < min_d:
                min_d = d
        has_col = 1 if max_cv > 1e-6 else 0
        metric = (has_col, max_cv, -min_d)  # maximize collision, then volume, then minimize distance
        dir_reports.append((ax, sgn, max_cv, min_d))
        if best_metric is None or metric > best_metric:
            best_metric = metric
            best_dir = (ax, sgn, v)

    print("Sweep direction reports (ax,sgn,maxCommonVol,minDist):")
    for ax, sgn, max_cv, min_d in dir_reports:
        print(f"  {ax} {sgn:+.0f}: maxCommonVol={max_cv:.6f}, minDist={min_d:.3f}")

    ax, sgn, v = best_dir
    print(f"Chosen sweep direction: axis={ax}, sign={sgn:+.0f}")

    # Collect problematic sweep positions (collision OR clearance < target)
    bad_positions = []
    worst = None  # (severity, t, pot_shape, closest_point_on_handle)

    for t in ts:
        dx = sgn * t * v[0]
        dy = sgn * t * v[1]
        dz = sgn * t * v[2]
        pot_t = coffeepot.translate((dx, dy, dz))
        cv = common_volume(handle, pot_t)
        d, pH, _ = dist_and_points(handle, pot_t)
        if cv > 1e-6 or d < clearance_gap:
            bad_positions.append((t, cv, d, pH))
            # severity: collision dominates, else how far below clearance
            severity = (1e9 + cv) if cv > 1e-6 else (clearance_gap - d)
            if worst is None or severity > worst[0]:
                worst = (severity, t, pot_t, pH)

    print(f"Bad sweep positions found: {len(bad_positions)}")
    if worst:
        print(f"Worst @ t={worst[1]:.1f}mm, refPointOnHandle={worst[3]}")

    # If nothing indicates collision/low-clearance (static or sweep), do nothing.
    if (iv0 < 1e-6 and d0 >= clearance_gap) and not bad_positions:
        print("No collision/low-clearance detected in static pose or along tested sweep; no changes applied.")
        return root

    # --- Build keep-out tool from problematic positions, dilated by (clearance+safety) ---
    shifts = [-dilate_r, 0.0, dilate_r]

    # Reduce tool size: sample at most N positions evenly from bad_positions
    N = 9
    if len(bad_positions) > N:
        # pick evenly spaced indices
        idxs = [int(round(i * (len(bad_positions) - 1) / (N - 1))) for i in range(N)]
        bad_positions_use = [bad_positions[i] for i in idxs]
    else:
        bad_positions_use = bad_positions

    tool_parts = []
    for t, cv, d, _ in bad_positions_use:
        dx = sgn * t * v[0]
        dy = sgn * t * v[1]
        dz = sgn * t * v[2]
        pot_t = coffeepot.translate((dx, dy, dz))
        for sx in shifts:
            for sy in shifts:
                for sz in shifts:
                    tool_parts.append(pot_t.translate((sx, sy, sz)))

    # Also include static pose as a safety
    for sx in shifts:
        for sy in shifts:
            for sz in shifts:
                tool_parts.append(coffeepot.translate((sx, sy, sz)))

    keepout = cq.Compound.makeCompound(tool_parts)
    print(f"Keep-out tool built: {len(tool_parts)} parts, dilate_r={dilate_r:.3f}mm")

    # Localize with a bounding box near worst interaction point to avoid carving whole handle
    handle_bb = handle.BoundingBox()
    if worst and worst[3] is not None:
        ref = worst[3]
    elif pH0 is not None:
        ref = pH0
    else:
        # fallback: midpoint between centers
        hb = handle_bb.center
        pb = pot_bb.center
        ref = (0.5 * (hb.x + pb.x), 0.5 * (hb.y + pb.y), 0.5 * (hb.z + pb.z))

    rx, ry, rz = ref
    # generous local box
    local_box = cq.Workplane("XY").box(260, 260, 260, centered=(True, True, True)).translate((rx, ry, rz)).val()
    keepout_local = cq.Shape(keepout.wrapped).intersect(cq.Shape(local_box.wrapped))

    # Perform cut
    try:
        cut_shape = handle.cut(keepout_local)
    except Exception as e:
        print(f"Handle cut failed: {e}")
        return root

    cut_solids = list(cut_shape.Solids())
    if not cut_solids:
        print("Cut produced no solids; leaving unchanged.")
        return root

    # Prefer keeping handle as a single main solid; if multiple, keep the largest
    cut_solids_sorted = sorted(cut_solids, key=lambda s: float(s.Volume()), reverse=True)
    new_handle = cut_solids_sorted[0]
    if len(cut_solids) != 1:
        print(f"WARNING: cut split handle into {len(cut_solids)} solids; keeping the largest by volume")

    # Report after
    ivf = common_volume(new_handle, coffeepot)
    df, _, _ = dist_and_points(new_handle, coffeepot)
    print(f"After cut (static): interVol={ivf:.6f} mm^3, minDist={df:.6f} mm")

    # Rebuild assembly compound with updated handle
    new_solids = []
    for i, s in enumerate(solids):
        new_solids.append(new_handle if i == handle_idx else s)
    result = cq.Compound.makeCompound(new_solids)

    print("Applied localized handle relief based on sweep keep-out volume.")
    return result
