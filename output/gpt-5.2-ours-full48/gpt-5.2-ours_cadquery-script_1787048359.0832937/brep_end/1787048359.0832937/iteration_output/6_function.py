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
        # x in [x0, x0+L]
        return cq.Solid.makeBox(L, L, L, cq.Vector(x0, -L / 2.0, -L / 2.0))

    def make_left_halfspace_box(x0: float):
        # x in [x0-L, x0]
        return cq.Solid.makeBox(L, L, L, cq.Vector(x0 - L, -L / 2.0, -L / 2.0))

    def mirror_about_x_plane(solid, x0: float):
        # Mirror about plane x=x0 (YZ plane shifted)
        moved = solid.translate((-x0, 0, 0))
        mirrored = cq.Workplane().newObject([moved]).mirror(mirrorPlane="YZ").val()
        return mirrored.translate((x0, 0, 0))

    # -------------------------
    # (2) Remove/delete cordholder geometry (small underside blocks near cord-exit end)
    # -------------------------
    removed_idxs = set()
    removal_dbg = []

    for i, s, vol, bb in per:
        if i == housing_i:
            continue

        # Near low-Y end of housing
        if bb.ymin > housing_bb.ymin + 80.0:
            continue

        # Near housing in X (exclude far-away plug)
        if abs(bb.center.x - midX) > (0.45 * housing_bb.xlen + 5.0):
            continue

        # Must protrude below the housing underside, but not be far below (exclude plug)
        if not (bb.zmin < housing_bb.zmin - 1.0):
            continue
        if bb.zmin < housing_bb.zmin - 90.0:
            continue

        # Small block-like solids only
        if vol > 60000.0 or vol < 50.0:
            continue
        if bb.xlen > 80.0 or bb.ylen > 80.0 or bb.zlen > 80.0:
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
    # Identify bracket/handle solid (the stand is assumed to be part of this)
    # -------------------------
    bracket_i = None
    bracket_bb = None
    bracket = None

    bracket_cands = []
    for i, s, vol, bb in per:
        if i == housing_i or i in removed_idxs:
            continue
        # Wide in X and lower than housing underside
        if bb.xlen < (housing_bb.xlen + 20.0):
            continue
        if bb.zmin > housing_bb.zmin - 1.0:
            continue
        # Not the cord/plug: cord tends to be long in Z and thin in Y; bracket has appreciable Y thickness
        if bb.ylen < 5.0:
            continue
        # Prefer parts near mid/high Y (mounting area)
        if not (housing_bb.ymin + 120.0 <= bb.center.y <= housing_bb.ymax - 5.0):
            continue
        bracket_cands.append((vol, i, s, bb))

    if bracket_cands:
        vol, bracket_i, bracket, bracket_bb = max(bracket_cands, key=lambda t: t[0])
        print(f"Bracket/stand candidate: Solid[{bracket_i}] V={vol:.3f} bb.x=({bracket_bb.xmin:.2f},{bracket_bb.xmax:.2f}) bb.zmin={bracket_bb.zmin:.2f}")
    else:
        print("WARNING: Could not identify bracket/stand solid; will skip mirroring/flattening on bracket.")

    # -------------------------
    # (1) Add mirrored handle/stand on opposite side if bracket is asymmetric
    # -------------------------
    bracket_modified = None
    if bracket is not None:
        right_box = make_right_halfspace_box(midX)
        left_box = make_left_halfspace_box(midX)

        try:
            right_half = cq.Workplane().newObject([bracket]).intersect(right_box).val()
            left_half = cq.Workplane().newObject([bracket]).intersect(left_box).val()
            vR = right_half.Volume() if right_half is not None else 0.0
            vL = left_half.Volume() if left_half is not None else 0.0
            vmax = max(vR, vL, 1e-9)
            asym = abs(vR - vL) / vmax
            print(f"Bracket symmetry check about x={midX:.3f}: vR={vR:.3f} vL={vL:.3f} asym={asym:.3f}")

            # If one side clearly has more geometry, mirror that side and union back
            if asym > 0.12:
                src_half = right_half if vR > vL else left_half
                mirrored = mirror_about_x_plane(src_half, midX)
                bracket_modified = cq.Workplane().newObject([bracket]).union(mirrored).val()
                print("Applied handle/stand mirroring by mirroring the larger half of the bracket across x=midX and unioning.")
            else:
                bracket_modified = bracket
                print("Bracket appears symmetric; no additional handle/stand created.")
        except Exception as e:
            print(f"WARNING: symmetry/mirroring failed: {e}")
            bracket_modified = bracket

    # -------------------------
    # (3) Cut/trim the bottom of the handles/stand to make a flat stable base
    # Apply to bracket (and to any other large, low, non-housing solids near mounting region)
    # -------------------------
    flattened_map = {}

    # Collect flatten targets: bracket plus any other non-housing solids that protrude below housing underside
    flatten_targets = []
    for i, s, vol, bb in per:
        if i == housing_i or i in removed_idxs:
            continue
        # Keep the cord/plug: far below housing or far in X
        if bb.zmin < housing_bb.zmin - 120.0:
            continue
        if abs(bb.center.x - midX) > (0.75 * housing_bb.xlen + 120.0) and bb.center.y < (housing_bb.ymin + 90.0):
            continue
        if bb.zmin > housing_bb.zmin - 1.0:
            continue
        # Reasonable size (avoid tiny fasteners etc)
        if vol < 5000.0:
            continue
        flatten_targets.append(i)

    flatten_targets = sorted(set(flatten_targets))
    if bracket_i is not None:
        if bracket_i not in flatten_targets:
            flatten_targets.append(bracket_i)
        flatten_targets = sorted(set(flatten_targets))

    print(f"Flatten targets (indices): {flatten_targets}")

    def cut_below_z(solid, z_cut: float, chamfer_mm: float = 0.8):
        # Box from z=z_cut-L to z=z_cut
        cut_box = cq.Solid.makeBox(L, L, L, cq.Vector(-L / 2.0, -L / 2.0, z_cut - L))
        out_wp = cq.Workplane().newObject([solid]).cut(cut_box)
        try:
            out_wp = out_wp.faces("<Z").edges().chamfer(chamfer_mm)
        except Exception:
            pass
        out = out_wp.val()
        if out is None or out.Volume() < 1e-6:
            return solid
        return out

    if flatten_targets:
        # compute current floor among targets, using bracket_modified where appropriate
        zmins = []
        for i in flatten_targets:
            if bracket_i is not None and i == bracket_i and bracket_modified is not None:
                zmins.append(bracket_modified.BoundingBox().zmin)
            else:
                zmins.append(solids[i].BoundingBox().zmin)

        z_floor = min(zmins)
        # Raise a little to create an actual flat pad
        flat_raise = 3.0
        z_cut = z_floor + flat_raise
        # Keep it below housing underside so stands remain the support
        z_cut_max = housing_bb.zmin - 2.0
        if z_cut > z_cut_max:
            z_cut = z_cut_max

        print(f"Bottom trim: z_floor={z_floor:.3f} -> z_cut={z_cut:.3f} (raise={flat_raise:.1f}, clamp_max={z_cut_max:.3f})")

        for i in flatten_targets:
            if bracket_i is not None and i == bracket_i and bracket_modified is not None:
                flattened_map[i] = cut_below_z(bracket_modified, z_cut)
            else:
                flattened_map[i] = cut_below_z(solids[i], z_cut)
    else:
        print("WARNING: No flatten targets found; skipping bottom trim.")

    # -------------------------
    # Build final compound
    # -------------------------
    new_solids = []
    for i, s in enumerate(solids):
        if i in removed_idxs:
            continue
        if i in flattened_map:
            new_solids.append(flattened_map[i])
        elif bracket_i is not None and i == bracket_i and bracket_modified is not None:
            # If bracket was modified but not flattened for some reason
            new_solids.append(bracket_modified)
        else:
            new_solids.append(s)

    print(
        f"Result solids: {len(new_solids)} (removed {len(removed_idxs)} cordholder solids, "
        f"modified_bracket={'yes' if bracket_modified is not None else 'no'}, flattened {len(flattened_map)} solids)"
    )

    return cq.Compound.makeCompound(new_solids)
