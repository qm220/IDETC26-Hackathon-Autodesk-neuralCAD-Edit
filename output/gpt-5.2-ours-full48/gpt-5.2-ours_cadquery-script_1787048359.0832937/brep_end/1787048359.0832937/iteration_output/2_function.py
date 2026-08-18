def my_cad_function(args):
    import cadquery as cq
    import os

    input_file = os.path.expanduser(args.get("input_file", ""))
    wp = cq.importers.importStep(input_file)
    shape = wp.val() if hasattr(wp, "val") else wp

    solids = list(shape.Solids())
    if not solids:
        print(f"Loaded STEP (no solids): {input_file}")
        return wp

    overall_bb = shape.BoundingBox()

    # --- Per-solid debug ---
    per = []
    print(f"Loaded STEP: {input_file}")
    print(f"Total solids: {len(solids)}")
    print(f"Overall bbox: xlen={overall_bb.xlen:.3f}, ylen={overall_bb.ylen:.3f}, zlen={overall_bb.zlen:.3f}")
    print(f"Overall center: ({overall_bb.center.x:.3f}, {overall_bb.center.y:.3f}, {overall_bb.center.z:.3f})")

    for i, s in enumerate(solids):
        bb = s.BoundingBox()
        vol = s.Volume()
        per.append((i, s, vol, bb))
        print(
            f"Solid[{i}]: V={vol:.3f} center=({bb.center.x:.3f},{bb.center.y:.3f},{bb.center.z:.3f}) "
            f"dims=({bb.xlen:.3f},{bb.ylen:.3f},{bb.zlen:.3f}) "
            f"xmin={bb.xmin:.3f} xmax={bb.xmax:.3f} ymin={bb.ymin:.3f} ymax={bb.ymax:.3f} zmin={bb.zmin:.3f} zmax={bb.zmax:.3f}"
        )

    # Identify main housing (largest volume solid) as a datum
    housing_i, housing_s, housing_vol, housing_bb = max(per, key=lambda t: t[2])
    midX = housing_bb.center.x
    print(f"Housing guess: Solid[{housing_i}] V={housing_vol:.3f} bb.x=({housing_bb.xmin:.3f},{housing_bb.xmax:.3f}) bb.zmin={housing_bb.zmin:.3f}")

    # -------------------------
    # (2) Remove/delete the cordholder
    # -------------------------
    # Heuristic deletion (only if it looks like a small underside block near cord-exit end):
    # - small-ish volume & dimensions
    # - near housing underside
    # - near one longitudinal end (low-Y or high-Y)
    # - not extremely low Z (avoid plug far away)
    removed_idxs = set()

    for i, s, vol, bb in per:
        if i == housing_i:
            continue

        # size/volume gating for small clip-like blocks
        if not (800.0 <= vol <= 25000.0):
            continue
        if bb.xlen > 60.0 or bb.ylen > 60.0 or bb.zlen > 70.0:
            continue

        # near the housing underside band
        if not (housing_bb.zmin - 30.0 <= bb.center.z <= housing_bb.zmin + 20.0):
            continue

        # near one end in Y
        end_band = 80.0
        if not (bb.center.y <= housing_bb.ymin + end_band or bb.center.y >= housing_bb.ymax - end_band):
            continue

        # avoid very-low-Z plug region
        if bb.center.z < housing_bb.zmin - 120.0:
            continue

        removed_idxs.add(i)

    print(f"Cordholder candidate solids to remove (by deletion): {sorted(removed_idxs)}")

    # -------------------------
    # Identify bracket/stand solid(s) and trim any integrated cordholder tabs
    # -------------------------
    bracket_like = []
    for i, s, vol, bb in per:
        if i == housing_i or i in removed_idxs:
            continue
        # typical external cradle band: thin in Y, wide in X, spans below housing
        if 10.0 <= bb.ylen <= 45.0 and bb.xlen >= housing_bb.xlen + 30.0 and bb.zmin < housing_bb.zmin - 2.0:
            # prefer the band near y~279-305 but keep slightly wider
            if 220.0 <= bb.center.y <= 340.0 and vol > 20000.0:
                bracket_like.append(i)

    bracket_like = sorted(set(bracket_like))
    print(f"Bracket-like solids (for tab removal / flattening): {bracket_like}")

    # Tool to remove a potential cordholder/tab cluster near the inner-bottom center of the cradle.
    # This cut is applied ONLY to the bracket-like solids to avoid harming the housing.
    def cut_integrated_cordholder_tabs(br_solid, br_bb):
        # A localized notch around x=midX, z near housing bottom; spans full bracket thickness in Y.
        ytool = max(br_bb.ylen + 20.0, 60.0)
        tool = (
            cq.Workplane("XY")
            .box(55.0, ytool, 32.0, centered=(True, True, True))
            .translate((midX, br_bb.center.y, housing_bb.zmin - 2.0))
        )
        try:
            before = br_solid.Volume()
            after_shape = cq.Workplane().newObject([br_solid]).cut(tool).val()
            after = after_shape.Volume()
            dv = before - after
            # If the cut barely changed anything, keep original (prevents accidental carving).
            if dv < 50.0:
                return br_solid, 0.0
            return after_shape, dv
        except Exception as e:
            print(f"WARNING: tab removal cut failed on bracket: {e}")
            return br_solid, 0.0

    bracket_cut_map = {}
    for bi in bracket_like:
        br = solids[bi]
        br_bb = br.BoundingBox()
        br2, dv = cut_integrated_cordholder_tabs(br, br_bb)
        bracket_cut_map[bi] = br2
        print(f"Bracket Solid[{bi}] tab-removal cut dV={dv:.3f}")

    # -------------------------
    # (1) Add mirrored handle/stand on opposite side if it exists only on one side as a separate solid
    # -------------------------
    # If handle is integrated into bracket/housing, mirroring isn't feasible at solid-level; in that case
    # the model is already symmetric and needs no action.
    handle_candidates = []
    for i, s, vol, bb in per:
        if i == housing_i or i in removed_idxs:
            continue
        if bb.zmin > housing_bb.zmin - 2.0:
            continue
        if bb.zlen < 40.0 or bb.ylen < 40.0:
            continue
        if bb.zlen > 0.85 * overall_bb.zlen:
            continue  # cord-like
        # relatively plate-like in X, and offset from mid-plane
        if bb.xlen < 90.0 and abs(bb.center.x - midX) > 0.25 * housing_bb.xlen:
            handle_candidates.append(i)

    handle_candidates = sorted(set(handle_candidates))
    pos = [i for i in handle_candidates if (solids[i].BoundingBox().center.x - midX) > 1e-6]
    neg = [i for i in handle_candidates if (solids[i].BoundingBox().center.x - midX) < -1e-6]
    print(f"Handle/stand separate-solid candidates: {handle_candidates} (+X={pos}, -X={neg})")

    mirrored_handles = []
    if (pos and not neg) or (neg and not pos):
        src = pos if pos else neg
        print(f"Mirroring handle solids {src} about x={midX:.3f}")
        for i in src:
            s = solids[i]
            # mirror about YZ plane at x=midX
            s_local = cq.Workplane().newObject([s.translate((-midX, 0, 0))]).val()
            s_m = cq.Workplane().newObject([s_local]).mirror(mirrorPlane="YZ").val().translate((midX, 0, 0))
            mirrored_handles.append(s_m)
    else:
        print("No handle mirroring needed (either both sides present, or handle integrated).")

    # -------------------------
    # (3) Flatten bottoms of the handles/stands for stable flat support
    # -------------------------
    # Determine which solids are likely to touch the ground (excluding cord/plug by Z-length and very low Z).
    def is_ground_contact_candidate(bb, vol):
        if vol < 1000.0:
            return False
        if bb.zlen > 0.85 * overall_bb.zlen:
            return False  # cord sweep
        if bb.center.z < housing_bb.zmin - 160.0:
            return False  # plug far below
        return bb.zmin < housing_bb.zmin - 2.0 and (housing_bb.ymin - 60.0) <= bb.center.y <= (housing_bb.ymax + 60.0)

    ground_idxs = []
    for i, s, vol, bb in per:
        if i == housing_i or i in removed_idxs:
            continue
        if is_ground_contact_candidate(bb, vol):
            ground_idxs.append(i)

    ground_idxs = sorted(set(ground_idxs + bracket_like))
    print(f"Ground-contact solids to flatten: {ground_idxs}")

    zmins = []
    for i in ground_idxs:
        # if bracket was already cut for tabs, use that version for bbox
        si = bracket_cut_map.get(i, solids[i])
        zmins.append(si.BoundingBox().zmin)
    for mh in mirrored_handles:
        zmins.append(mh.BoundingBox().zmin)

    flattened_map = {}
    if zmins:
        z_floor = min(zmins)
        z_cut = z_floor + 2.0
        print(f"Flattening: z_floor={z_floor:.3f} => z_cut={z_cut:.3f}")

        cut_box = (
            cq.Workplane("XY")
            .box(20000, 20000, 20000, centered=(True, True, True))
            .translate((0, 0, z_cut - 10000))
        )

        for i in ground_idxs:
            base = bracket_cut_map.get(i, solids[i])
            try:
                flat = cq.Workplane().newObject([base]).cut(cut_box).val()
                if flat.Volume() < 1e-6:
                    flat = base
                flattened_map[i] = flat
            except Exception as e:
                print(f"WARNING: flatten cut failed on Solid[{i}]: {e}")
                flattened_map[i] = base

        # also flatten mirrored handles
        mh_flat = []
        for mh in mirrored_handles:
            try:
                mh2 = cq.Workplane().newObject([mh]).cut(cut_box).val()
                if mh2.Volume() < 1e-6:
                    mh2 = mh
                mh_flat.append(mh2)
            except Exception as e:
                print(f"WARNING: flatten cut failed on mirrored handle: {e}")
                mh_flat.append(mh)
        mirrored_handles = mh_flat
    else:
        print("No ground-contact candidates detected; skipping bottom flattening.")

    # -------------------------
    # Build final solids
    # -------------------------
    new_solids = []
    for i, s in enumerate(solids):
        if i in removed_idxs:
            continue

        # prefer: bracket tab-cut version; then flattened version; else original
        if i in flattened_map:
            new_solids.append(flattened_map[i])
        elif i in bracket_cut_map:
            new_solids.append(bracket_cut_map[i])
        else:
            new_solids.append(s)

    new_solids.extend(mirrored_handles)

    print(
        f"Result solids: {len(new_solids)} (removed {len(removed_idxs)} solids by deletion, "
        f"added {len(mirrored_handles)} mirrored handle solids)"
    )

    return cq.Compound.makeCompound(new_solids)
