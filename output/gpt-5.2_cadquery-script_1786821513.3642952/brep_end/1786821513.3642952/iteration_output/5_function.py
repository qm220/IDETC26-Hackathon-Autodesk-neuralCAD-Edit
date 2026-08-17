def my_cad_function(args):
    import os
    import cadquery as cq

    if "input_file" not in args:
        print("No input_file provided")
        return None

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    print(f"Loaded STEP: {input_file}")
    try:
        print(f"Valid: {shape.isValid()}")
    except Exception:
        pass

    solids = list(shape.Solids())
    print(f"Solids: {len(solids)}, Faces: {len(shape.Faces())}, Edges: {len(shape.Edges())}")
    if not solids:
        return model

    # Work on the largest solid (main part)
    main_i, main_solid = max(enumerate(solids), key=lambda t: t[1].Volume())
    other_solids = [s for i, s in enumerate(solids) if i != main_i]

    bb = main_solid.BoundingBox()
    y_front = bb.ymax
    xmid = 0.5 * (bb.xmin + bb.xmax)
    zmid = 0.5 * (bb.zmin + bb.zmax)
    print(
        f"Main solid BBox: xmin={bb.xmin:.3f} xmax={bb.xmax:.3f} ymin={bb.ymin:.3f} ymax={bb.ymax:.3f} "
        f"zmin={bb.zmin:.3f} zmax={bb.zmax:.3f}"
    )

    # --- Find candidate cylindrical faces near axis and near front (likely hub/bore region) ---
    cyl_cands = []
    for idx, f in enumerate(main_solid.Faces()):
        try:
            if str(f.geomType()).upper() != "CYLINDER":
                continue
        except Exception:
            continue

        fb = f.BoundingBox()
        fc = fb.center

        # Prefer axis ~Y cylinders (xlen ~ zlen) and centered near (xmid,zmid)
        if abs(fb.xlen - fb.zlen) > 1.5:
            continue

        radial_center = ((fc.x - xmid) ** 2 + (fc.z - zmid) ** 2) ** 0.5
        if radial_center > 3.0:
            continue

        # Must be close to the front
        y_to_front = y_front - fb.ymax
        if y_to_front > 3.0:
            continue

        r = 0.25 * (fb.xlen + fb.zlen)
        if r < 4.0 or r > 45.0:
            continue

        # Score: prioritize closer to front, then larger radius
        score = 3.0 * y_to_front - 0.03 * r + 0.05 * radial_center
        cyl_cands.append((score, y_to_front, r, idx, fb, fc))

    cyl_cands.sort(key=lambda t: t[0])
    print(f"Front/axis CYLINDER candidates: {len(cyl_cands)}")
    for k, (score, ytf, r, idx, fb, fc) in enumerate(cyl_cands[:10]):
        print(
            f"  cand[{k}] faceIndex={idx} score={score:.4f} y_to_front={ytf:.3f} r~{r:.3f} "
            f"y=[{fb.ymin:.3f},{fb.ymax:.3f}] center=({fc.x:.3f},{fc.y:.3f},{fc.z:.3f})"
        )

    if not cyl_cands:
        print("No suitable front/axis CYLINDER found; returning original")
        return model

    # Pick a stable target: among the few closest-to-front, choose the largest radius
    top = cyl_cands[:8]
    _, ytf, r_target, face_idx, fb, fc = max(top, key=lambda t: t[2])
    cx, cz = fc.x, fc.z

    print(
        f"Selected target cylinder: faceIndex={face_idx}, r_target~{r_target:.3f}, "
        f"axisCenter=({cx:.3f},{cz:.3f}), face_y_to_front={ytf:.3f}"
    )

    # --- Build two possible chamfer cuts (internal hole vs external boss) and choose by smallest positive volume removal ---
    chamfer = 1.0
    eps_y = 0.03
    eps_r = 0.02
    margin = 4.0

    # Chamfer is applied at the FRONT side only
    y0 = y_front - chamfer - eps_y
    y1 = y_front + eps_y
    dy = y1 - y0

    wp0 = cq.Workplane("XZ").workplane(offset=y0).center(cx, cz)

    # Internal hole chamfer: radius increases toward the front
    r_back_hole = max(0.1, r_target + eps_r)
    r_front_hole = max(0.1, r_target + chamfer + eps_r)
    hole_frustum = (
        wp0.circle(r_back_hole)
        .workplane(offset=dy)
        .circle(r_front_hole)
        .loft(combine=False, ruled=True)
    )
    hole_inner = wp0.circle(max(0.05, r_target - 0.20)).extrude(dy)
    hole_cutter = hole_frustum.cut(hole_inner)

    # External boss chamfer: radius decreases toward the front
    r_outer_boss = max(0.1, r_target + chamfer + margin)
    r_back_boss = max(0.1, r_target - eps_r)
    r_front_boss = max(0.1, r_target - chamfer - eps_r)
    boss_outer = wp0.circle(r_outer_boss).extrude(dy)
    boss_inner_frustum = (
        wp0.circle(r_back_boss)
        .workplane(offset=dy)
        .circle(r_front_boss)
        .loft(combine=False, ruled=True)
    )
    boss_cutter = boss_outer.cut(boss_inner_frustum)

    orig_vol = main_solid.Volume()

    def _try_cut(cutter, label):
        try:
            res = cq.Workplane(obj=main_solid).cut(cutter).val()
            try:
                valid = res.isValid()
            except Exception:
                valid = True
            vol = res.Volume()
            removed = orig_vol - vol
            print(f"{label}: valid={valid} vol_removed={removed:.6f} (orig={orig_vol:.6f} new={vol:.6f})")
            if (not valid) or (removed <= 1e-6):
                return None
            return (removed, res)
        except Exception as e:
            print(f"{label}: cut failed: {e}")
            return None

    hole_try = _try_cut(hole_cutter, "HOLE_CHAMFER")
    boss_try = _try_cut(boss_cutter, "BOSS_CHAMFER")

    chosen = None
    if hole_try and boss_try:
        # pick the smaller positive removal (more likely just replacing a local fillet)
        chosen = hole_try if hole_try[0] <= boss_try[0] else boss_try
        print(f"Chose {'HOLE_CHAMFER' if chosen is hole_try else 'BOSS_CHAMFER'} by minimal volume removal")
    elif hole_try:
        chosen = hole_try
        print("Chose HOLE_CHAMFER (only successful positive cut)")
    elif boss_try:
        chosen = boss_try
        print("Chose BOSS_CHAMFER (only successful positive cut)")
    else:
        print("Neither chamfer cut produced a valid positive change; returning original")
        return model

    main_res = chosen[1]

    # Recombine solids as a compound
    if other_solids:
        final_shape = cq.Compound.makeCompound([main_res] + other_solids)
    else:
        final_shape = main_res

    print("Applied 1mm chamfer at the front-center (replacing fillet via selected cut).")
    return final_shape
