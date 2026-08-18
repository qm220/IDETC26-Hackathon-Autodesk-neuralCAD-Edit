def my_cad_function(args):
    import cadquery as cq
    import os

    # Purpose:
    # Resolve interference between the external handle (U-bracket) and the coffeepot.
    # Robust approach:
    # 1) Identify handle solid.
    # 2) Identify coffeepot as the solid that most intersects the handle (or nearest if none).
    # 3) Create a conservative clearance keep-out by dilating the coffeepot (via translated copies).
    # 4) Apply a LOCAL relief cut to the handle, depth-limited along the dominant direction from handle->pot,
    #    to avoid severing the handle into multiple solids.
    # 5) Validate: no intersection, and >= target clearance where possible.

    clearance_gap = 2.0  # mm required clearance
    safety = 0.3         # mm numerical + manufacturing margin
    r = float(clearance_gap + safety)

    # Depths to try for local pocket (mm). Keep shallow first to avoid splitting handle.
    depth_trials = [4.0, 6.0, 8.0, 12.0, 18.0, 25.0]

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

    # Housing is largest volume
    vols = [float(s.Volume()) for s in solids]
    housing_idx = max(range(len(solids)), key=lambda k: vols[k])

    # Identify handle (U-bracket) by bounding box heuristics
    handle_candidates = []
    for i, s in enumerate(solids):
        if i == housing_idx:
            continue
        bb, vol = bbinfo(s)
        # U-bracket spans wide in X, significant Z, moderate Y band
        if bb.xlen > 220 and bb.zlen > 140 and 8 < bb.ylen < 90 and vol > 5e4:
            handle_candidates.append(i)

    if not handle_candidates:
        # fallback: best scoring non-housing
        best = None
        for i, s in enumerate(solids):
            if i == housing_idx:
                continue
            bb, vol = bbinfo(s)
            score = 0.0
            score += 2.0 * bb.xlen
            score += 1.2 * bb.zlen
            if 8 < bb.ylen < 90:
                score += 300.0
            score += min(vol / 1e4, 200.0)
            if best is None or score > best[0]:
                best = (score, i)
        if best:
            handle_candidates = [best[1]]

    print(f"Handle candidate indices: {handle_candidates}")
    if not handle_candidates:
        raise RuntimeError("Could not identify handle solid")

    handle_idx = handle_candidates[0]
    handle = solids[handle_idx]
    handle_bb = handle.BoundingBox()

    # OCP helpers
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape

    def common_shape(a: cq.Shape, b: cq.Shape):
        com = BRepAlgoAPI_Common(a.wrapped, b.wrapped)
        com.Build()
        if not com.IsDone():
            return None
        return cq.Shape(com.Shape())

    def common_volume(a: cq.Shape, b: cq.Shape) -> float:
        shp = common_shape(a, b)
        if shp is None:
            return 0.0
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

    # Find coffeepot:
    # Prefer the solid with maximum intersection volume with handle.
    inter_list = []
    for i, s in enumerate(solids):
        if i in (housing_idx, handle_idx):
            continue
        vol_i = common_volume(handle, s)
        if vol_i > 0:
            inter_list.append((vol_i, i))

    inter_list.sort(reverse=True, key=lambda t: t[0])
    if inter_list:
        pot_idx = inter_list[0][1]
        print("Intersecting solids with handle (top 5):", inter_list[:5])
    else:
        # If nothing intersects, pick the nearest substantial solid as "coffeepot"
        near = []
        for i, s in enumerate(solids):
            if i in (housing_idx, handle_idx):
                continue
            bb, vol = bbinfo(s)
            if vol < 3e4:
                continue
            d = min_dist(handle, s)
            near.append((d, i))
        near.sort(key=lambda t: t[0])
        if not near:
            print("No intersecting or nearby candidate found; leaving model unchanged.")
            return root
        pot_idx = near[0][1]
        print("No static intersections detected; nearest candidate chosen:", near[:5])

    coffeepot = solids[pot_idx]
    pot_bb = coffeepot.BoundingBox()
    print(
        f"Selected coffeepot idx={pot_idx} "
        f"center=({pot_bb.center.x:.2f},{pot_bb.center.y:.2f},{pot_bb.center.z:.2f}) "
        f"bb=({pot_bb.xlen:.1f},{pot_bb.ylen:.1f},{pot_bb.zlen:.1f})"
    )

    iv0 = common_volume(handle, coffeepot)
    d0 = min_dist(handle, coffeepot)
    print(f"Before edit: interVol={iv0:.6f} mm^3, minDist={d0:.6f} mm")

    # If already well clear, do nothing
    if iv0 < 1e-6 and d0 >= clearance_gap:
        print("No collision and clearance >= target in static position; no changes applied.")
        return root

    # Create conservative dilation of coffeepot by union of translated copies (L-infinity ball).
    # This avoids reliance on BRepOffsetAPI (which failed in prior run).
    shifts = [-r, 0.0, r]
    pot_copies = []
    for dx in shifts:
        for dy in shifts:
            for dz in shifts:
                # include all, including (0,0,0)
                pot_copies.append(coffeepot.translate((dx, dy, dz)))
    dilated_tool = cq.Compound.makeCompound(pot_copies)
    print(f"Built dilated keep-out tool using {len(pot_copies)} translated copies, r={r:.3f}mm")

    # Determine a reference point for the relief region
    ref_pt = None
    com_shp = common_shape(handle, coffeepot)
    if com_shp is not None:
        try:
            bb = com_shp.BoundingBox()
            if bb.xlen > 1e-6 or bb.ylen > 1e-6 or bb.zlen > 1e-6:
                ref_pt = (float(bb.center.x), float(bb.center.y), float(bb.center.z))
        except Exception:
            ref_pt = None

    if ref_pt is None:
        # fallback to midpoint between centers
        ref_pt = (
            0.5 * (handle_bb.center.x + pot_bb.center.x),
            0.5 * (handle_bb.center.y + pot_bb.center.y),
            0.5 * (handle_bb.center.z + pot_bb.center.z),
        )

    # Direction from handle to pot
    vx = float(pot_bb.center.x - handle_bb.center.x)
    vy = float(pot_bb.center.y - handle_bb.center.y)
    vz = float(pot_bb.center.z - handle_bb.center.z)

    # Choose dominant axis for depth-limiting slab
    ax = max([(abs(vx), 'X'), (abs(vy), 'Y'), (abs(vz), 'Z')], key=lambda t: t[0])[1]
    sign = 1.0
    if ax == 'X':
        sign = 1.0 if vx >= 0 else -1.0
    elif ax == 'Y':
        sign = 1.0 if vy >= 0 else -1.0
    else:
        sign = 1.0 if vz >= 0 else -1.0

    print(f"Relief direction axis={ax}, sign={sign:+.0f}, ref_pt={tuple(round(v,3) for v in ref_pt)}")

    def make_halfspace_slab(depth: float):
        # Make an axis-aligned slab box that keeps the 'pot-facing' side and limits cut depth into the handle.
        bigx = handle_bb.xlen * 3.0 + 500.0
        bigy = handle_bb.ylen * 3.0 + 500.0
        bigz = handle_bb.zlen * 3.0 + 500.0

        # Start with large box; then adjust along chosen axis to create half-space with controlled depth.
        # We'll define [min, max] on axis such that we include everything toward the pot,
        # and only extend depth into the opposite direction by `depth`.
        rx, ry, rz = ref_pt
        if ax == 'X':
            if sign > 0:
                xmin, xmax = rx - depth, rx + 2000.0
            else:
                xmin, xmax = rx - 2000.0, rx + depth
            xlen = xmax - xmin
            xcen = 0.5 * (xmin + xmax)
            box = cq.Workplane('YZ').box(bigy, bigz, xlen, centered=(True, True, True)).translate((xcen, 0, 0))
            return box
        if ax == 'Y':
            if sign > 0:
                ymin, ymax = ry - depth, ry + 2000.0
            else:
                ymin, ymax = ry - 2000.0, ry + depth
            ylen = ymax - ymin
            ycen = 0.5 * (ymin + ymax)
            box = cq.Workplane('XZ').box(bigx, bigz, ylen, centered=(True, True, True)).translate((0, ycen, 0))
            return box
        # Z
        if sign > 0:
            zmin, zmax = rz - depth, rz + 2000.0
        else:
            zmin, zmax = rz - 2000.0, rz + depth
        zlen = zmax - zmin
        zcen = 0.5 * (zmin + zmax)
        box = cq.Workplane('XY').box(bigx, bigy, zlen, centered=(True, True, True)).translate((0, 0, zcen))
        return box

    # Try progressive local relief depths until collision cleared and handle remains a single solid
    best = None
    for depth in depth_trials:
        slab = make_halfspace_slab(depth)
        # localize the tool to avoid through-cut
        try:
            tool_local = dilated_tool.intersect(slab.val()) if hasattr(slab, 'val') else dilated_tool.intersect(slab)
        except Exception:
            # CadQuery intersect sometimes expects Shapes; ensure we have a Shape
            tool_local = cq.Shape(dilated_tool.wrapped).intersect(cq.Shape(slab.val().wrapped))

        try:
            cut_raw = handle.cut(tool_local)
        except Exception as e:
            print(f"Depth {depth:.1f}mm: cut failed: {e}")
            continue

        cut_solids = list(cut_raw.Solids()) if hasattr(cut_raw, 'Solids') else []
        if not cut_solids:
            print(f"Depth {depth:.1f}mm: no solids after cut (invalid result)")
            continue

        # Prefer single solid handle; if multiple, this depth is too aggressive / severed handle
        if len(cut_solids) != 1:
            print(f"Depth {depth:.1f}mm: cut split handle into {len(cut_solids)} solids; rejecting")
            continue

        handle_cut = cut_solids[0]
        iv = common_volume(handle_cut, coffeepot)
        d = min_dist(handle_cut, coffeepot)
        print(f"Depth {depth:.1f}mm: interVol={iv:.6f}, minDist={d:.6f}")

        ok = (iv < 1e-6) and (d >= (clearance_gap - 0.05))
        if ok:
            best = handle_cut
            print(f"Selected depth {depth:.1f}mm (collision resolved with clearance)")
            break

        # If collision cleared but clearance not met, keep as candidate, continue trying deeper
        if iv < 1e-6 and best is None:
            best = handle_cut

    if best is None:
        print("Failed to produce a safe local relief without splitting handle; leaving model unchanged.")
        return root

    # Rebuild compound with updated handle
    new_solids = []
    for i, s in enumerate(solids):
        new_solids.append(best if i == handle_idx else s)

    result = cq.Compound.makeCompound(new_solids)

    # Final report
    ivf = common_volume(best, coffeepot)
    df = min_dist(best, coffeepot)
    print(f"After edit: interVol={ivf:.6f} mm^3, minDist={df:.6f} mm")
    if ivf >= 1e-6:
        print("WARNING: Still intersecting after edit.")
    if df < clearance_gap:
        print("WARNING: Clearance below target after edit (but collision may be removed).")

    print("Updated handle with depth-limited local relief to remove coffeepot interference.")
    return result
