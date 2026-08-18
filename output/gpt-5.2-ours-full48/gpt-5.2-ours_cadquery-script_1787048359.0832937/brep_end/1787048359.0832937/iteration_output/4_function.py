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
    print(f"Loaded STEP: {input_file}")
    print(f"Total solids: {len(solids)}")
    print(f"Overall bbox: xlen={overall_bb.xlen:.3f}, ylen={overall_bb.ylen:.3f}, zlen={overall_bb.zlen:.3f}")
    print(f"Overall center: ({overall_bb.center.x:.3f}, {overall_bb.center.y:.3f}, {overall_bb.center.z:.3f})")

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

    # Housing datum: largest volume solid
    housing_i, housing_s, housing_vol, housing_bb = max(per, key=lambda t: t[2])
    midX = housing_bb.center.x
    print(
        f"Housing guess: Solid[{housing_i}] V={housing_vol:.3f} bb.x=({housing_bb.xmin:.3f},{housing_bb.xmax:.3f}) "
        f"bb.y=({housing_bb.ymin:.3f},{housing_bb.ymax:.3f}) bb.zmin={housing_bb.zmin:.3f}"
    )

    def is_electrical_region(bb):
        # cord/plug cluster tends to be near low-Y end
        return bb.center.y < (housing_bb.ymin + 90.0)

    # -------------------------
    # (2) Remove/delete cordholder geometry
    # -------------------------
    # Heuristic tuned to remove small underside blocks near cord exit, but not plug/prongs.
    removed_idxs = set()
    for i, s, vol, bb in per:
        if i == housing_i:
            continue

        # must be near the low-Y end where cord exits
        if not is_electrical_region(bb):
            continue

        # must be close to housing in X (cordholder on device underside, not plug end far away)
        if abs(bb.center.x - midX) > (0.7 * housing_bb.xlen + 30.0):
            continue

        # near underside of housing
        if not (housing_bb.zmin - 40.0 <= bb.center.z <= housing_bb.zmin + 30.0):
            continue

        # avoid deleting far-below plug components
        if bb.center.z < housing_bb.zmin - 90.0:
            continue

        # small-ish block-like solids
        if not (150.0 <= vol <= 80000.0):
            continue
        if bb.xlen > 90.0 or bb.ylen > 90.0 or bb.zlen > 90.0:
            continue

        removed_idxs.add(i)

    print(f"Cordholder candidate solids to remove (by deletion): {sorted(removed_idxs)}")

    # -------------------------
    # (1) Add mirrored handle/stand on opposite side (if it exists as separate solid on only one side)
    # -------------------------
    handle_candidates = []
    for i, s, vol, bb in per:
        if i == housing_i or i in removed_idxs:
            continue
        if is_electrical_region(bb):
            continue

        # must reach below housing underside to act as stand
        if bb.zmin > housing_bb.zmin - 5.0:
            continue

        # strap-like proportions
        if not (bb.ylen > 60.0 and bb.zlen > 50.0):
            continue
        if not (4.0 <= bb.xlen <= 90.0):
            continue

        # near side walls
        if abs(bb.center.x - midX) < (0.35 * housing_bb.xlen):
            continue

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
    # (3) Flatten bottom of handles/stands for stable resting
    # -------------------------
    # Identify bracket/stand-carrier solids near housing that dip below housing.
    bracket_like = []
    for i, s, vol, bb in per:
        if i == housing_i or i in removed_idxs:
            continue
        if is_electrical_region(bb):
            continue

        if bb.zmin > housing_bb.zmin - 5.0:
            continue

        # wide in X across device is typical of cradle/bracket
        if bb.xlen < housing_bb.xlen + 20.0:
            continue

        # moderate Y thickness
        if not (6.0 <= bb.ylen <= 80.0):
            continue

        if vol < 15000.0:
            continue

        # located around mid-length of device
        if not (housing_bb.ymin + 80.0 <= bb.center.y <= housing_bb.ymax - 10.0):
            continue

        bracket_like.append(i)

    bracket_like = sorted(set(bracket_like))
    print(f"Bracket-like solids (stand carrier) for flattening: {bracket_like}")

    to_flatten_idxs = sorted(set(bracket_like + handle_candidates))

    zmins = []
    for i in to_flatten_idxs:
        zmins.append(solids[i].BoundingBox().zmin)
    for mh in mirrored_handles:
        zmins.append(mh.BoundingBox().zmin)

    flattened_map = {}
    if zmins:
        z_floor = min(zmins)

        # Make a *clear* flat by trimming a bit more than last iteration.
        # Clamp so stands remain below housing underside.
        flat_raise = 8.0
        z_cut = z_floor + flat_raise
        z_cut_max = housing_bb.zmin - 3.0
        if z_cut > z_cut_max:
            z_cut = z_cut_max
        print(f"Flattening stands: z_floor={z_floor:.3f} => z_cut={z_cut:.3f} (raise={flat_raise:.1f}, clamp_max={z_cut_max:.3f})")

        cut_box = (
            cq.Workplane("XY")
            .box(50000, 50000, 50000, centered=(True, True, True))
            .translate((0, 0, z_cut - 25000))
        )

        def flatten_and_ease(solid):
            base = solid
            try:
                out = cq.Workplane().newObject([base]).cut(cut_box)
                # small edge treatment on the new bottom, if possible
                try:
                    out = out.faces("<Z").edges().chamfer(0.8)
                except Exception:
                    pass
                val = out.val()
                if val.Volume() < 1e-6:
                    return base
                return val
            except Exception as e:
                print(f"WARNING: flatten cut failed: {e}")
                return base

        for i in to_flatten_idxs:
            flattened_map[i] = flatten_and_ease(solids[i])

        mh_flat = []
        for mh in mirrored_handles:
            mh_flat.append(flatten_and_ease(mh))
        mirrored_handles = mh_flat
    else:
        print("WARNING: No stand-related solids detected for flattening; skipping bottom trim.")

    # -------------------------
    # Build final compound
    # -------------------------
    new_solids = []
    for i, s in enumerate(solids):
        if i in removed_idxs:
            continue
        if i in flattened_map:
            new_solids.append(flattened_map[i])
        else:
            new_solids.append(s)

    new_solids.extend(mirrored_handles)

    print(
        f"Result solids: {len(new_solids)} (removed {len(removed_idxs)} solids by deletion, "
        f"added {len(mirrored_handles)} mirrored handle solids, flattened {len(flattened_map)} solids)"
    )

    return cq.Compound.makeCompound(new_solids)
