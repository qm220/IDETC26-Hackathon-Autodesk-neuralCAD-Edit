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

    # Datum: housing = largest volume
    housing_i, housing_s, housing_vol, housing_bb = max(per, key=lambda t: t[2])
    midX = housing_bb.center.x
    print(f"Housing guess: Solid[{housing_i}] V={housing_vol:.3f} bb.x=({housing_bb.xmin:.3f},{housing_bb.xmax:.3f}) bb.zmin={housing_bb.zmin:.3f}")

    # Helper: classify electrical (cord/plug) region by being near very low Y end (cord exit region)
    # NOTE: based on observed model: cord/plug cluster is near y~0..80.
    def is_electrical_region(bb):
        return bb.center.y < (housing_bb.ymin + 90.0)

    # -------------------------
    # (2) Remove/delete the cordholder feature/geometry
    # -------------------------
    removed_idxs = set()

    # Heuristic: small-ish solids near housing underside AND near cord-exit end (low Y), within housing X span.
    for i, s, vol, bb in per:
        if i == housing_i:
            continue

        # keep anything obviously far away (plug end)
        if abs(bb.center.x - midX) > (0.65 * housing_bb.xlen + 40.0):
            continue

        if not is_electrical_region(bb):
            continue

        # small block-like
        if not (200.0 <= vol <= 50000.0):
            continue
        if bb.xlen > 80.0 or bb.ylen > 80.0 or bb.zlen > 80.0:
            continue

        # near housing underside
        if not (housing_bb.zmin - 35.0 <= bb.center.z <= housing_bb.zmin + 25.0):
            continue

        # avoid deleting long slender electrical geometry
        if bb.zlen > 120.0 or bb.xlen > 120.0:
            continue

        # avoid deleting any part that is far below the housing (typical plug/prongs area)
        if bb.center.z < housing_bb.zmin - 90.0:
            continue

        removed_idxs.add(i)

    print(f"Cordholder candidate solids to remove (by deletion): {sorted(removed_idxs)}")

    # -------------------------
    # (1) Add mirrored handle/stand on opposite side (if only one exists as a separate solid)
    # -------------------------
    # Detect separate handle/stand solids: plate/strap-like, near housing sides, not in electrical region.
    handle_candidates = []
    for i, s, vol, bb in per:
        if i == housing_i or i in removed_idxs:
            continue
        if is_electrical_region(bb):
            continue

        # must extend downward below housing bottom to act as stand/handle
        if bb.zmin > housing_bb.zmin - 5.0:
            continue

        # strap-like sizing (tuned to observed images)
        if not (bb.ylen > 60.0 and bb.zlen > 50.0):
            continue
        if not (5.0 <= bb.xlen <= 80.0):
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
    # (3) Cut/trim the bottom of the handles to create stable flat contact
    # -------------------------
    # IMPORTANT FIX vs last iteration:
    # - Do NOT include cord/plug solids in flattening determination.
    # - Determine the flattening plane from stand/handle/bracket solids near the housing (not lowest global Z).

    # Bracket/stand carrier solid(s): wide in X, thin-ish in Y, below housing.
    bracket_like = []
    for i, s, vol, bb in per:
        if i == housing_i or i in removed_idxs:
            continue
        if is_electrical_region(bb):
            continue

        if bb.zmin > housing_bb.zmin - 5.0:
            continue
        if bb.xlen < housing_bb.xlen + 20.0:
            continue
        if not (8.0 <= bb.ylen <= 60.0):
            continue
        if vol < 20000.0:
            continue

        # keep those around mid/upper device length (typical cradle location)
        if not (housing_bb.ymin + 120.0 <= bb.center.y <= housing_bb.ymax - 20.0):
            continue

        bracket_like.append(i)

    bracket_like = sorted(set(bracket_like))
    print(f"Bracket-like solids (stand carrier) for flattening: {bracket_like}")

    # Determine solids to flatten: bracket-like + any separate handle solids + mirrored handles.
    to_flatten_idxs = sorted(set(bracket_like + handle_candidates))

    # Compute z_floor from ONLY these stand-related solids (not electrical)
    zmins = []
    for i in to_flatten_idxs:
        zmins.append(solids[i].BoundingBox().zmin)
    for mh in mirrored_handles:
        zmins.append(mh.BoundingBox().zmin)

    flattened_map = {}
    if zmins:
        z_floor = min(zmins)
        # raise plane slightly to create a reasonable flat pad
        z_cut = z_floor + 2.0
        print(f"Flattening stands: z_floor={z_floor:.3f} => z_cut={z_cut:.3f} (only stand-related solids)")

        # Big box below plane; cutting it off yields a flat bottom at z_cut.
        cut_box = (
            cq.Workplane("XY")
            .box(50000, 50000, 50000, centered=(True, True, True))
            .translate((0, 0, z_cut - 25000))
        )

        for i in to_flatten_idxs:
            base = solids[i]
            try:
                flat = cq.Workplane().newObject([base]).cut(cut_box).val()
                # if cut nuked the solid unexpectedly, revert
                if flat.Volume() < 1e-6:
                    flat = base
                flattened_map[i] = flat
            except Exception as e:
                print(f"WARNING: flatten cut failed on Solid[{i}]: {e}")
                flattened_map[i] = base

        # flatten mirrored handles too
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
        print("WARNING: No stand-related solids detected for flattening; skipping bottom trim.")

    # -------------------------
    # Build final solids
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
