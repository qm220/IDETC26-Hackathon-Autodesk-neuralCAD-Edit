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
        # cable sweep: long in Z, thin in Y, modest volume
        return (bb.zlen > 160.0 and bb.ylen < 10.0 and vol < 250000.0)

    def is_plug_like(bb, vol):
        # far away in -Z direction and not tiny
        return (bb.zmin < housing_bb.zmin - 120.0 and vol > 1200.0)

    cord_like = set()
    plug_like = set()
    for i, s, vol, bb in per:
        if i == housing_i:
            continue
        if is_cord_like(bb, vol):
            cord_like.add(i)
        if is_plug_like(bb, vol):
            plug_like.add(i)

    print(f"Cord-like solids (excluded from removal/flatten/mirror): {sorted(cord_like)}")
    print(f"Plug-like solids (excluded from removal/flatten/mirror): {sorted(plug_like)}")

    # -------------------------
    # (2) Remove/delete cordholder geometry
    # Broadened heuristic: small solids under housing underside, near the low-Y/front region, within housing X span.
    # -------------------------
    removed_idxs = set()
    removal_dbg = []

    for i, s, vol, bb in per:
        if i == housing_i or i in cord_like or i in plug_like:
            continue

        # Must live under/near underside
        if not (bb.zmax <= housing_bb.zmin + 15.0):
            continue
        if bb.zmin < housing_bb.zmin - 90.0:
            continue

        # Prefer front region where cord exits/cordholder usually sits
        if bb.ymin > housing_bb.ymin + 180.0:
            continue

        # Must be close in X to housing (avoid plug/prongs far out)
        if abs(bb.center.x - midX) > (0.65 * housing_bb.xlen):
            continue

        # Size/volume bounds (cordholders are small blocks)
        max_dim = max(bb.xlen, bb.ylen, bb.zlen)
        if not (200.0 < vol < 250000.0):
            continue
        if max_dim > 70.0:
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
    # Identify bracket/cradle candidate (often the big U-shaped band around the housing)
    # -------------------------
    bracket_i = None
    bracket = None
    bracket_bb = None

    bracket_cands = []
    for i, s, vol, bb in per:
        if i == housing_i or i in removed_idxs or i in cord_like or i in plug_like:
            continue
        # wide in X and protrudes below housing
        if bb.xlen < housing_bb.xlen + 15.0:
            continue
        if bb.zmin >= housing_bb.zmin - 1.0:
            continue
        # lives around mid-to-upper Y (mounting band region)
        if not (housing_bb.ymin + 120.0 <= bb.center.y <= housing_bb.ymax - 20.0):
            continue
        if vol < 15000.0:
            continue
        bracket_cands.append((vol, i, s, bb))

    if bracket_cands:
        vol, bracket_i, bracket, bracket_bb = max(bracket_cands, key=lambda t: t[0])
        print(
            f"Bracket/stand candidate: Solid[{bracket_i}] V={vol:.3f} "
            f"bb.x=({bracket_bb.xmin:.2f},{bracket_bb.xmax:.2f}) bb.y=({bracket_bb.ymin:.2f},{bracket_bb.ymax:.2f}) bb.z=({bracket_bb.zmin:.2f},{bracket_bb.zmax:.2f})"
        )
    else:
        print("WARNING: Could not identify bracket/cradle solid.")

    modified = {}  # int index -> cq.Solid replacement
    added_solids = []

    # -------------------------
    # (1) Add mirrored handle/stand on opposite side (if missing)
    # Handle-like solids heuristic: protrude beyond housing in X, relatively narrow in X, tall-ish in Y/Z.
    # -------------------------
    handle_like = []
    for i, s, vol, bb in per:
        if i == housing_i or i in removed_idxs or i in cord_like or i in plug_like:
            continue
        if bracket_i is not None and i == bracket_i:
            continue

        protrude_pos = bb.xmax - housing_bb.xmax
        protrude_neg = housing_bb.xmin - bb.xmin
        if max(protrude_pos, protrude_neg) < 8.0:
            continue

        # Narrow-ish in X (strap/handle), but with meaningful height
        if bb.xlen > 80.0:
            continue
        if not (bb.ylen > 60.0 or bb.zlen > 60.0):
            continue

        # Should be near the device along Y (not far away like plug body)
        if not (housing_bb.ymin - 10.0 <= bb.center.y <= housing_bb.ymax + 10.0):
            continue

        handle_like.append((i, s, vol, bb))

    pos_handles = [t for t in handle_like if t[3].center.x > midX]
    neg_handles = [t for t in handle_like if t[3].center.x < midX]
    print(f"Handle-like solids detected: {[t[0] for t in handle_like]} pos={len(pos_handles)} neg={len(neg_handles)}")

    if (len(pos_handles) > 0) ^ (len(neg_handles) > 0):
        src = pos_handles if len(pos_handles) > 0 else neg_handles
        for (i, s, vol, bb) in src:
            try:
                m = mirror_about_x_plane(s, midX)
                added_solids.append(m)
                print(f"Mirrored handle-like Solid[{i}] across x={midX:.3f} and added as new solid")
            except Exception as e:
                print(f"WARNING: mirroring handle-like Solid[{i}] failed: {e}")
    else:
        print("Handle-like mirroring not needed (already present on both sides or none detected).")

    # If bracket is clearly one-sided (rare here), mirror its larger half into the other side.
    def mirror_if_one_sided(solid, x0: float):
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
                print("Applied bracket half-mirroring (bracket appeared one-sided).")
            else:
                modified[bracket_i] = bracket
        except Exception as e:
            print(f"WARNING: bracket symmetry/mirroring failed: {e}")
            modified[bracket_i] = bracket

    # -------------------------
    # (3) Cut/trim the bottom of the handles/stands to create stable flat contact
    # We flatten all solids (except housing/cord/plug) that protrude below housing underside.
    # Increase cut amount to create a more noticeable flat (vs previous 3mm).
    # -------------------------
    def cut_below_z(solid, z_cut: float, chamfer_mm: float = 1.0):
        cut_box = cq.Solid.makeBox(L, L, L, cq.Vector(-L / 2.0, -L / 2.0, z_cut - L))
        out_wp = cq.Workplane().newObject([solid]).cut(cut_box)
        try:
            out_wp = out_wp.faces("<Z").edges().chamfer(chamfer_mm)
        except Exception:
            pass
        out = out_wp.val()
        return out if (out is not None and out.Volume() > 1e-6) else solid

    # Build a list of candidates to flatten by original indices
    flatten_idxs = []
    for i, s, vol, bb in per:
        if i == housing_i or i in removed_idxs or i in cord_like or i in plug_like:
            continue
        if bb.zmin < housing_bb.zmin - 1.0 and vol > 3500.0:
            flatten_idxs.append(i)

    flatten_idxs = sorted(set(flatten_idxs))
    print(f"Flatten candidate indices: {flatten_idxs}")

    # Determine z_floor among flatten candidates (including bracket after potential modification)
    if flatten_idxs:
        zmins = []
        for i in flatten_idxs:
            base = modified.get(i, solids[i])
            zmins.append(base.BoundingBox().zmin)
        z_floor = min(zmins)

        # Choose raise based on available clearance to housing
        diff = housing_bb.zmin - z_floor
        clearance_to_housing = 3.0
        max_raise = max(0.0, diff - clearance_to_housing)
        # target raise: 60% of available gap, but at least 8mm, capped by max_raise
        target_raise = max(8.0, 0.60 * diff)
        raise_amt = min(target_raise, max_raise)
        z_cut = z_floor + raise_amt

        # Safety clamp: never cut above housing underside minus clearance
        z_cut_max = housing_bb.zmin - clearance_to_housing
        if z_cut > z_cut_max:
            z_cut = z_cut_max

        print(
            f"Bottom trim: z_floor={z_floor:.3f}, housing_zmin={housing_bb.zmin:.3f}, diff={diff:.3f} -> "
            f"raise={raise_amt:.3f}, z_cut={z_cut:.3f} (clearance={clearance_to_housing:.1f})"
        )

        for i in flatten_idxs:
            base = modified.get(i, solids[i])
            modified[i] = cut_below_z(base, z_cut, chamfer_mm=1.0)
    else:
        print("WARNING: No flatten candidates found; skipping bottom trimming.")

    # -------------------------
    # Build final solids list
    # -------------------------
    new_solids = []
    for i, s in enumerate(solids):
        if i in removed_idxs:
            continue
        if i in modified and isinstance(modified[i], cq.Solid):
            new_solids.append(modified[i])
        else:
            new_solids.append(s)

    # Append added mirrored handle solids (if any)
    new_solids.extend(added_solids)

    print(
        f"Result solids: {len(new_solids)} (removed={len(removed_idxs)}, modified={len([k for k in modified.keys() if isinstance(k,int)])}, added={len(added_solids)})"
    )

    return cq.Compound.makeCompound(new_solids)
