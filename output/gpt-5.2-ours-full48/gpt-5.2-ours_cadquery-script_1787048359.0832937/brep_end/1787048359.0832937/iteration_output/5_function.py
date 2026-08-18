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

    # Housing guess: largest solid by volume
    housing_i, housing_s, housing_vol, housing_bb = max(per, key=lambda t: t[2])
    midX = housing_bb.center.x
    print(
        f"Housing guess: Solid[{housing_i}] V={housing_vol:.3f} "
        f"bb.x=({housing_bb.xmin:.3f},{housing_bb.xmax:.3f}) "
        f"bb.y=({housing_bb.ymin:.3f},{housing_bb.ymax:.3f}) "
        f"bb.z=({housing_bb.zmin:.3f},{housing_bb.zmax:.3f}) midX={midX:.3f}"
    )

    # Heuristic: cord/plug region is clustered near low-Y end of the device
    def is_electrical_region(bb):
        return bb.center.y < (housing_bb.ymin + 85.0)

    # -------------------------
    # (2) Remove/delete cordholder geometry
    # -------------------------
    # Goal: remove small block-like solids near the underside and near the low-Y end,
    # but keep the cord and plug which are typically farther away in X/Z.
    removed_idxs = set()
    cordholder_dbg = []
    for i, s, vol, bb in per:
        if i == housing_i:
            continue

        # Must be near cord-exit end
        if bb.ymax > (housing_bb.ymin + 60.0):
            continue

        # Must be physically near the device body in X (exclude far-away plug body)
        if abs(bb.center.x - midX) > (0.65 * housing_bb.xlen + 25.0):
            continue

        # Near underside of housing
        if not (housing_bb.zmin - 25.0 <= bb.center.z <= housing_bb.zmin + 35.0):
            continue

        # Exclude far-below plug/prongs geometry
        if bb.zmin < housing_bb.zmin - 120.0:
            continue

        # Block-like small solids
        if not (80.0 <= vol <= 30000.0):
            continue
        if bb.xlen > 60.0 or bb.ylen > 60.0 or bb.zlen > 60.0:
            continue

        removed_idxs.add(i)
        cordholder_dbg.append((i, vol, bb.xlen, bb.ylen, bb.zlen, bb.center.x, bb.center.y, bb.center.z))

    print(f"Cordholder solids removed by deletion: {sorted(removed_idxs)}")
    for (i, vol, xl, yl, zl, cx, cy, cz) in cordholder_dbg:
        print(f"  removed Solid[{i}] V={vol:.1f} dims=({xl:.2f},{yl:.2f},{zl:.2f}) center=({cx:.2f},{cy:.2f},{cz:.2f})")

    # -------------------------
    # (1) Add mirrored handle/stand on opposite side (if handle exists as separate solid on only one side)
    # -------------------------
    stand_candidates = []
    for i, s, vol, bb in per:
        if i == housing_i or i in removed_idxs:
            continue
        if is_electrical_region(bb):
            continue

        # Must be external to housing in X and extend below housing underside (a stand)
        external_x = (bb.xmax > housing_bb.xmax + 1.0) or (bb.xmin < housing_bb.xmin - 1.0)
        if not external_x:
            continue
        if bb.zmin > housing_bb.zmin - 1.0:
            continue

        # Slender-ish stand proportions
        if not (2.0 <= bb.xlen <= 90.0):
            continue
        if not (20.0 <= bb.ylen <= 260.0):
            continue
        if not (25.0 <= bb.zlen <= 280.0):
            continue
        if vol > 350000.0:
            continue

        # Near side walls (avoid wide cradle bands)
        if abs(bb.center.x - midX) < (0.45 * housing_bb.xlen):
            continue

        stand_candidates.append(i)

    stand_candidates = sorted(set(stand_candidates))
    pos = [i for i in stand_candidates if (solids[i].BoundingBox().center.x - midX) > 1e-6]
    neg = [i for i in stand_candidates if (solids[i].BoundingBox().center.x - midX) < -1e-6]
    print(f"Stand/handle separate-solid candidates: {stand_candidates} (+X={pos}, -X={neg})")

    mirrored_stands = []
    if (pos and not neg) or (neg and not pos):
        src = pos if pos else neg
        print(f"Mirroring stand solids {src} about plane x={midX:.3f}")
        for i in src:
            s = solids[i]
            # Mirror about YZ at x=midX
            s_local = cq.Workplane().newObject([s.translate((-midX, 0, 0))]).val()
            s_m = cq.Workplane().newObject([s_local]).mirror(mirrorPlane="YZ").val().translate((midX, 0, 0))
            mirrored_stands.append(s_m)
    else:
        print("No stand mirroring applied (either both sides already present, or stand not a separate solid).")

    # -------------------------
    # (3) Cut/trim bottoms to create stable flat contact
    # -------------------------
    # We flatten any likely stand / cradle solids around the device mid-to-high Y region.
    bracket_like = []
    for i, s, vol, bb in per:
        if i == housing_i or i in removed_idxs:
            continue
        if is_electrical_region(bb):
            continue

        if bb.zmin > housing_bb.zmin - 1.0:
            continue

        # Wide cradle / bracket band: spans most of device width
        if bb.xlen < (housing_bb.xlen + 15.0):
            continue

        # Reasonable thickness in Y
        if not (4.0 <= bb.ylen <= 90.0):
            continue

        # Located around the mounting region (not at extreme ends)
        if not (housing_bb.ymin + 120.0 <= bb.center.y <= housing_bb.ymax - 5.0):
            continue

        if vol < 8000.0:
            continue

        bracket_like.append(i)

    bracket_like = sorted(set(bracket_like))
    print(f"Bracket/cradle solids to consider for flattening: {bracket_like}")

    # Flatten targets = bracket_like + stand candidates (if separate)
    to_flatten_idxs = sorted(set(bracket_like + stand_candidates))

    zmins = []
    for i in to_flatten_idxs:
        zmins.append(solids[i].BoundingBox().zmin)
    for ms in mirrored_stands:
        zmins.append(ms.BoundingBox().zmin)

    flattened_map = {}
    if zmins:
        z_floor = min(zmins)

        # Create a flat by trimming slightly above the very lowest point.
        # Clamp so we don't cut above housing underside (stands must remain below housing).
        flat_raise = 6.0
        z_cut = z_floor + flat_raise
        z_cut_max = housing_bb.zmin - 2.0
        if z_cut > z_cut_max:
            z_cut = z_cut_max

        print(f"Flattening targets: z_floor={z_floor:.3f} => z_cut={z_cut:.3f} (raise={flat_raise:.1f}, clamp_max={z_cut_max:.3f})")

        cut_box = (
            cq.Workplane("XY")
            .box(50000, 50000, 50000, centered=(True, True, True))
            .translate((0, 0, z_cut - 25000))
        )

        def flatten_and_chamfer(solid):
            base = solid
            try:
                out = cq.Workplane().newObject([base]).cut(cut_box)
                # Lightly break sharp edges on the new bottom face
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
            flattened_map[i] = flatten_and_chamfer(solids[i])

        mirrored_stands = [flatten_and_chamfer(ms) for ms in mirrored_stands]
    else:
        print("WARNING: No stand/bracket targets detected for flattening; skipping bottom trim.")

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

    new_solids.extend(mirrored_stands)

    print(
        f"Result solids: {len(new_solids)} (removed {len(removed_idxs)} cordholder solids, "
        f"mirrored {len(mirrored_stands)} stand solids, flattened {len(flattened_map)} solids)"
    )

    return cq.Compound.makeCompound(new_solids)
