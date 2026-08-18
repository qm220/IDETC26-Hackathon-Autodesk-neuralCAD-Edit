def my_cad_function(args):
    import cadquery as cq
    import os
    import math

    input_file = os.path.expanduser(args.get("input_file", ""))
    wp = cq.importers.importStep(input_file)
    shape = wp.val() if hasattr(wp, "val") else wp

    solids = list(shape.Solids())
    if not solids:
        print(f"Loaded STEP (no solids): {input_file}")
        return wp

    overall_bb = shape.BoundingBox()
    midX = overall_bb.center.x

    print(f"Loaded STEP: {input_file}")
    print(f"Total solids: {len(solids)}")
    print(f"Overall bbox: xlen={overall_bb.xlen:.3f}, ylen={overall_bb.ylen:.3f}, zlen={overall_bb.zlen:.3f}")
    print(f"Overall center: ({overall_bb.center.x:.3f}, {overall_bb.center.y:.3f}, {overall_bb.center.z:.3f})")

    # --- Per-solid debug ---
    per = []
    for i, s in enumerate(solids):
        bb = s.BoundingBox()
        vol = s.Volume()
        per.append((i, s, vol, bb))
        print(
            f"Solid[{i}]: V={vol:.3f} center=({bb.center.x:.3f},{bb.center.y:.3f},{bb.center.z:.3f}) "
            f"dims=({bb.xlen:.3f},{bb.ylen:.3f},{bb.zlen:.3f}) "
            f"xmin={bb.xmin:.3f} xmax={bb.xmax:.3f} ymin={bb.ymin:.3f} ymax={bb.ymax:.3f} zmin={bb.zmin:.3f} zmax={bb.zmax:.3f}"
        )

    # Identify main housing (largest volume solid) as a datum for "underside" Z.
    housing_i, housing_s, housing_vol, housing_bb = max(per, key=lambda t: t[2])
    print(f"Housing guess: Solid[{housing_i}] V={housing_vol:.3f} zmin={housing_bb.zmin:.3f}")

    # -------------------------
    # (2) Remove cordholder
    # -------------------------
    # Heuristic: small blocks near the housing underside and near the cord-exit end (small Y), close to center in X.
    # Avoid plug (very low Z) by requiring zmin not too close to overall zmin.
    total_vol = sum(v for _, _, v, _ in per)

    cordholder_idxs = []
    for i, s, vol, bb in per:
        if i == housing_i:
            continue
        # small-ish solids
        if not (500.0 <= vol <= total_vol * 0.01):
            continue
        # near center in X (cordholder near device, not far-away plug)
        if abs(bb.center.x - midX) > 0.35 * overall_bb.xlen:
            continue
        # near the housing underside band
        if bb.zmax > housing_bb.zmin + 40.0:
            continue
        if bb.zmin < overall_bb.zmin + 40.0:
            continue
        # near the cord exit end (small Y region)
        if bb.center.y > 120.0:
            continue
        # modest size
        if bb.xlen > 80.0 or bb.ylen > 80.0 or bb.zlen > 120.0:
            continue

        cordholder_idxs.append(i)

    cordholder_idxs = sorted(set(cordholder_idxs))
    print(f"Cordholder candidates (to remove): {cordholder_idxs}")

    # -------------------------
    # (1) Add mirrored stand/handle on opposite side
    # -------------------------
    # The requested "black handle" visually matches a stand-like strap/ear near the mounting band (Y around ~279-305 in model.json).
    # Strategy: find stand-like solids in that Y zone that extend below the housing underside; if only present on one side in X,
    # mirror them about x=midX.

    def is_stand_like(bb, vol):
        # near bracket/ear Y zone
        if not (200.0 <= bb.center.y <= 340.0):
            return False
        # extends below housing bottom
        if bb.zmin > housing_bb.zmin - 5.0:
            return False
        # not the huge housing
        if vol > housing_vol * 0.6:
            return False
        # avoid cord/plug: cord is very long in Z
        if bb.zlen > 0.75 * overall_bb.zlen:
            return False
        return True

    stand_idxs = []
    for i, s, vol, bb in per:
        if i == housing_i:
            continue
        if is_stand_like(bb, vol):
            # prefer off-center in X (a separate stand/ear)
            if abs(bb.center.x - midX) > 0.18 * overall_bb.xlen:
                stand_idxs.append(i)

    stand_idxs = sorted(set(stand_idxs))
    print(f"Stand-like separate solids: {stand_idxs}")

    mirrored_stands = []
    if stand_idxs:
        pos = [i for i in stand_idxs if (solids[i].BoundingBox().center.x - midX) > 1e-6]
        neg = [i for i in stand_idxs if (solids[i].BoundingBox().center.x - midX) < -1e-6]
        print(f"Stand sides detected: +X={pos}, -X={neg}")

        if (pos and not neg) or (neg and not pos):
            src = pos if pos else neg
            print(f"Mirroring stand solids {src} about x={midX:.3f}")
            for i in src:
                s = solids[i]
                s_local = cq.Workplane().newObject([s.translate((-midX, 0, 0))]).val()
                s_m = cq.Workplane().newObject([s_local]).mirror(mirrorPlane="YZ").val().translate((midX, 0, 0))
                mirrored_stands.append(s_m)
        else:
            print("Both sides already have stand-like solids; no mirroring needed.")
    else:
        print("No separate stand-like solids found; assuming stand geometry is integrated into a larger bracket solid (already symmetric) or absent.")

    # -------------------------
    # (3) Flatten bottoms of the handles/stands
    # -------------------------
    # Prefer flattening the stand solids if found; otherwise flatten the bracket-like solid(s) near y~292 that extend below housing.

    flatten_target_idxs = []
    if stand_idxs:
        flatten_target_idxs = list(stand_idxs)
    else:
        # fallback: choose non-housing solids near y~279-305 that dip below housing, likely the external cradle/bracket
        for i, s, vol, bb in per:
            if i == housing_i:
                continue
            if 250.0 <= bb.center.y <= 320.0 and bb.zmin < housing_bb.zmin - 5.0 and bb.ylen <= 60.0 and vol < housing_vol * 0.4:
                flatten_target_idxs.append(i)
        flatten_target_idxs = sorted(set(flatten_target_idxs))

    print(f"Flatten targets (existing solids): {flatten_target_idxs}")

    # Determine cut plane from the lowest point among the intended stand solids (including mirrored ones if present).
    zmins = []
    for i in flatten_target_idxs:
        zmins.append(solids[i].BoundingBox().zmin)
    for ms in mirrored_stands:
        zmins.append(ms.BoundingBox().zmin)

    # If nothing to flatten, just proceed with removals/mirroring.
    do_flatten = len(zmins) > 0
    if do_flatten:
        z_floor = min(zmins)
        # cut a bit above lowest to create a flat pad
        z_cut = z_floor + 2.0
        print(f"Flattening: z_floor={z_floor:.3f} => z_cut={z_cut:.3f}")
        # cutting box removes everything below z_cut
        cut_box = cq.Workplane("XY").box(20000, 20000, 20000, centered=(True, True, True)).translate((0, 0, z_cut - 10000))

        # Replace flattened versions
        flattened_map = {}
        for i in flatten_target_idxs:
            s = solids[i]
            try:
                flat = cq.Workplane().newObject([s]).cut(cut_box).val()
                # If cut removed everything, keep original
                if flat.Volume() < 1e-6:
                    flat = s
                flattened_map[i] = flat
            except Exception as e:
                print(f"WARNING: flatten cut failed on Solid[{i}]: {e}")
                flattened_map[i] = s

        # Flatten mirrored stand solids too
        mirrored_stands_flat = []
        for ms in mirrored_stands:
            try:
                msf = cq.Workplane().newObject([ms]).cut(cut_box).val()
                if msf.Volume() < 1e-6:
                    msf = ms
                mirrored_stands_flat.append(msf)
            except Exception as e:
                print(f"WARNING: flatten cut failed on mirrored stand: {e}")
                mirrored_stands_flat.append(ms)
        mirrored_stands = mirrored_stands_flat
    else:
        print("No flattening targets identified; skipping stand bottom trimming.")

    # -------------------------
    # Build result solids
    # -------------------------
    new_solids = []
    removed = set(cordholder_idxs)

    for i, s in enumerate(solids):
        if i in removed:
            continue
        if do_flatten and i in locals().get('flattened_map', {}):
            new_solids.append(flattened_map[i])
        else:
            new_solids.append(s)

    # Add mirrored stands (already flattened if flattening ran)
    new_solids.extend(mirrored_stands)

    print(f"Result solids: {len(new_solids)} (removed {len(removed)} cordholder candidate solids, added {len(mirrored_stands)} mirrored stand solids)")

    return cq.Compound.makeCompound(new_solids)
