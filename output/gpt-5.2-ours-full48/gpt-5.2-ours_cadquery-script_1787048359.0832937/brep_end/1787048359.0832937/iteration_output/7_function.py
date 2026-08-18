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

    # Housing = largest by volume
    housing_i, housing_s, housing_vol, housing_bb = max(per, key=lambda t: t[2])
    midX = housing_bb.center.x
    print(
        f"Housing guess: Solid[{housing_i}] V={housing_vol:.3f} "
        f"bb.x=({housing_bb.xmin:.3f},{housing_bb.xmax:.3f}) "
        f"bb.y=({housing_bb.ymin:.3f},{housing_bb.ymax:.3f}) "
        f"bb.z=({housing_bb.zmin:.3f},{housing_bb.zmax:.3f}) midX={midX:.3f}"
    )

    L = 50000.0

    def make_right_halfspace_box(x0: float):
        return cq.Solid.makeBox(L, L, L, cq.Vector(x0, -L / 2.0, -L / 2.0))

    def make_left_halfspace_box(x0: float):
        return cq.Solid.makeBox(L, L, L, cq.Vector(x0 - L, -L / 2.0, -L / 2.0))

    def mirror_about_x_plane(solid, x0: float):
        moved = solid.translate((-x0, 0, 0))
        mirrored = cq.Workplane().newObject([moved]).mirror(mirrorPlane="YZ").val()
        return mirrored.translate((x0, 0, 0))

    # --- classify cord/plug-ish solids to avoid accidental edits ---
    def is_cord_like(bb, vol):
        # long in Z, thin in Y and X
        return (bb.zlen > 140.0 and bb.ylen < 8.0 and bb.xlen < 260.0 and vol < 200000.0)

    def is_plug_like(bb, vol):
        # far from housing in Z and relatively chunky
        return (bb.zmin < housing_bb.zmin - 120.0 and vol > 1000.0)

    cord_like = set()
    plug_like = set()
    for i, s, vol, bb in per:
        if i == housing_i:
            continue
        if is_cord_like(bb, vol):
            cord_like.add(i)
        if is_plug_like(bb, vol) and abs(bb.center.y - housing_bb.ymin) < 120.0:
            plug_like.add(i)
    print(f"Cord-like solids (excluded from removal/flatten/mirror): {sorted(cord_like)}")
    print(f"Plug-like solids (excluded from removal/flatten/mirror): {sorted(plug_like)}")

    # -------------------------
    # (2) Remove/delete cordholder geometry
    # Robust heuristic: small solids near low-Y end, close to housing in X, and only slightly below housing underside
    # -------------------------
    removed_idxs = set()
    removal_dbg = []

    for i, s, vol, bb in per:
        if i == housing_i or i in cord_like or i in plug_like:
            continue

        # Low-Y region near cord exit (front/bottom area)
        if bb.ymax > housing_bb.ymin + 70.0:
            continue

        # Close to housing in X (cordholders sit under body)
        if abs(bb.center.x - midX) > (0.55 * housing_bb.xlen + 10.0):
            continue

        # Slightly below housing underside (not far below like plug)
        dz = housing_bb.zmin - bb.zmin
        if not (1.0 < dz < 45.0):
            continue

        # Small blocks
        if not (100.0 < vol < 80000.0):
            continue
        if bb.xlen > 90.0 or bb.ylen > 90.0 or bb.zlen > 90.0:
            continue

        removed_idxs.add(i)
        removal_dbg.append((i, vol, bb.xlen, bb.ylen, bb.zlen, bb.center.x, bb.center.y, bb.center.z, bb.zmin, bb.zmax))

    print(f"Cordholder removal: deleting solids {sorted(removed_idxs)}")
    for (i, vol, xl, yl, zl, cx, cy, cz, zmin, zmax) in removal_dbg:
        print(
            f"  removed Solid[{i}] V={vol:.1f} dims=({xl:.2f},{yl:.2f},{zl:.2f}) "
            f"center=({cx:.2f},{cy:.2f},{cz:.2f}) z=({zmin:.2f},{zmax:.2f})"
        )

    # -------------------------
    # Identify bracket / stand candidate(s)
    # Prefer a part that is wider in X than housing and lives in mounting region in Y.
    # -------------------------
    bracket_i = None
    bracket = None
    bracket_bb = None

    bracket_cands = []
    for i, s, vol, bb in per:
        if i == housing_i or i in removed_idxs or i in cord_like or i in plug_like:
            continue
        # wide-ish in X (wrap/strap) and protrudes below housing
        if bb.xlen < housing_bb.xlen + 15.0:
            continue
        if bb.zmin > housing_bb.zmin - 1.0:
            continue
        # lives around mounting region
        if not (housing_bb.ymin + 140.0 <= bb.center.y <= housing_bb.ymax - 20.0):
            continue
        if vol < 20000.0:
            continue
        bracket_cands.append((vol, i, s, bb))

    if bracket_cands:
        vol, bracket_i, bracket, bracket_bb = max(bracket_cands, key=lambda t: t[0])
        print(
            f"Bracket/stand candidate: Solid[{bracket_i}] V={vol:.3f} "
            f"bb.x=({bracket_bb.xmin:.2f},{bracket_bb.xmax:.2f}) bb.y=({bracket_bb.ymin:.2f},{bracket_bb.ymax:.2f}) bb.zmin={bracket_bb.zmin:.2f}"
        )
    else:
        print("WARNING: Could not identify bracket/stand solid.")

    # -------------------------
    # (1) Add mirrored handle/stand on opposite side
    # Two-pass approach:
    #   A) If bracket exists and is clearly one-sided, mirror the larger half into the other side.
    #   B) If no bracket or bracket is symmetric, look for any stand-like solids protruding beyond housing on only one side and mirror them.
    # -------------------------
    modified = {}  # i -> modified solid

    def mirror_if_one_sided(solid, x0: float, asym_thresh: float = 0.12):
        right_box = make_right_halfspace_box(x0)
        left_box = make_left_halfspace_box(x0)
        right_half = cq.Workplane().newObject([solid]).intersect(right_box).val()
        left_half = cq.Workplane().newObject([solid]).intersect(left_box).val()
        vR = right_half.Volume() if right_half else 0.0
        vL = left_half.Volume() if left_half else 0.0
        vmax = max(vR, vL, 1e-9)
        asym = abs(vR - vL) / vmax
        return asym, vR, vL, right_half, left_half

    if bracket is not None:
        try:
            asym, vR, vL, right_half, left_half = mirror_if_one_sided(bracket, midX)
            print(f"Bracket symmetry check about x={midX:.3f}: vR={vR:.3f} vL={vL:.3f} asym={asym:.3f}")
            if asym > 0.12:
                src_half = right_half if vR > vL else left_half
                mirrored = mirror_about_x_plane(src_half, midX)
                modified[bracket_i] = cq.Workplane().newObject([bracket]).union(mirrored).val()
                print("Applied handle/stand mirroring: bracket was one-sided, mirrored larger half and unioned.")
            else:
                modified[bracket_i] = bracket
                print("Bracket appears symmetric; no bracket mirroring needed.")
        except Exception as e:
            print(f"WARNING: bracket symmetry/mirroring failed: {e}")
            modified[bracket_i] = bracket

    # Fallback: mirror any stand-like solids that exist only on one side
    stand_like = []
    for i, s, vol, bb in per:
        if i == housing_i or i in removed_idxs or i in cord_like or i in plug_like:
            continue
        if bracket_i is not None and i == bracket_i:
            continue
        # must protrude outboard of housing on either +X or -X
        protrude_pos = bb.xmax - housing_bb.xmax
        protrude_neg = housing_bb.xmin - bb.xmin
        if max(protrude_pos, protrude_neg) < 8.0:
            continue
        # likely a stand: tall in Z or Y relative to thickness
        slender = (bb.zlen > 60.0 and bb.xlen < 35.0) or (bb.ylen > 60.0 and bb.xlen < 35.0)
        if not slender:
            continue
        # near housing in Y
        if not (housing_bb.ymin - 5.0 <= bb.center.y <= housing_bb.ymax + 5.0):
            continue
        stand_like.append((i, s, vol, bb, protrude_pos, protrude_neg))

    if stand_like:
        # Determine if we have missing mirror partners: count +X and -X stands
        pos = [t for t in stand_like if t[3].center.x > midX]
        neg = [t for t in stand_like if t[3].center.x < midX]
        print(f"Stand-like solids detected (non-bracket): {[t[0] for t in stand_like]} pos={len(pos)} neg={len(neg)}")
        if (len(pos) > 0) ^ (len(neg) > 0):
            # mirror all stands from existing side
            src = pos if len(pos) > 0 else neg
            for (i, s, vol, bb, pp, pn) in src:
                mirrored = mirror_about_x_plane(s, midX)
                # union into original solid if it is self-contained; otherwise keep as additional solid
                # Here we add as a NEW solid to preserve assembly.
                modified[f"add_mirror_{i}"] = mirrored
            print("Applied fallback mirroring: mirrored stand-like solids to the opposite side.")
        else:
            print("Fallback mirroring: stands exist on both sides (or none); no action.")
    else:
        print("No additional stand-like solids found for fallback mirroring.")

    # -------------------------
    # (3) Cut/trim the bottom of the handles/stands to create stable flat contact
    # Only cut solids that protrude below housing underside (i.e., feet/stands/bracket), never the housing.
    # -------------------------
    def cut_below_z(solid, z_cut: float, chamfer_mm: float = 0.8):
        cut_box = cq.Solid.makeBox(L, L, L, cq.Vector(-L / 2.0, -L / 2.0, z_cut - L))
        out_wp = cq.Workplane().newObject([solid]).cut(cut_box)
        try:
            out_wp = out_wp.faces("<Z").edges().chamfer(chamfer_mm)
        except Exception:
            pass
        out = out_wp.val()
        return out if (out is not None and out.Volume() > 1e-6) else solid

    # Determine which solids to flatten (by index), based on original list
    flatten_idxs = []
    for i, s, vol, bb in per:
        if i == housing_i or i in removed_idxs or i in cord_like or i in plug_like:
            continue
        # protrudes below housing
        if bb.zmin < housing_bb.zmin - 1.0 and bb.zmin > housing_bb.zmin - 120.0:
            # avoid tiny bits
            if vol > 4000.0:
                flatten_idxs.append(i)

    flatten_idxs = sorted(set(flatten_idxs))
    print(f"Flatten candidate indices (pre-modified): {flatten_idxs}")

    # Compute floor among flatten candidates using modified shapes where applicable
    if flatten_idxs:
        zmins = []
        for i in flatten_idxs:
            if i in modified and isinstance(i, int) and modified[i] is not None:
                zmins.append(modified[i].BoundingBox().zmin)
            else:
                zmins.append(solids[i].BoundingBox().zmin)
        z_floor = min(zmins)
        flat_raise = 3.0
        z_cut = z_floor + flat_raise
        # keep stands still lower than housing underside
        z_cut_max = housing_bb.zmin - 2.0
        if z_cut > z_cut_max:
            z_cut = z_cut_max
        print(f"Bottom trim: z_floor={z_floor:.3f} -> z_cut={z_cut:.3f} (raise={flat_raise:.1f}, clamp_max={z_cut_max:.3f})")

        for i in flatten_idxs:
            base = modified.get(i, solids[i]) if isinstance(i, int) else solids[i]
            modified[i] = cut_below_z(base, z_cut)
    else:
        print("WARNING: No flatten candidates found; skipping bottom trimming.")

    # -------------------------
    # Build final solids list
    #   - remove removed_idxs
    #   - replace any modified indexed solids
    #   - add any extra mirrored solids inserted by fallback mirroring (keys are strings)
    # -------------------------
    new_solids = []
    for i, s in enumerate(solids):
        if i in removed_idxs:
            continue
        if i in modified and isinstance(modified[i], cq.Solid):
            new_solids.append(modified[i])
        else:
            new_solids.append(s)

    # append additional solids (fallback mirrors)
    added = [k for k in modified.keys() if not isinstance(k, int)]
    for k in added:
        try:
            new_solids.append(modified[k])
        except Exception:
            pass

    print(
        f"Result solids: {len(new_solids)} "
        f"(removed {len(removed_idxs)} cordholder solids; modified indexed solids: {sorted([k for k in modified.keys() if isinstance(k,int)])}; "
        f"added mirrored solids: {len(added)})"
    )

    return cq.Compound.makeCompound(new_solids)
