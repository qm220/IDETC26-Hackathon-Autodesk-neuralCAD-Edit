def my_cad_function(args):
    import os
    import math
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

    # Work on the largest solid as the main part
    main_i, main_solid = max(enumerate(solids), key=lambda t: t[1].Volume())
    other_solids = [s for i, s in enumerate(solids) if i != main_i]

    bb = main_solid.BoundingBox()
    xmid = 0.5 * (bb.xmin + bb.xmax)
    zmid = 0.5 * (bb.zmin + bb.zmax)
    y_front = bb.ymax
    print(
        f"Main solid BBox: xmin={bb.xmin:.3f} xmax={bb.xmax:.3f} ymin={bb.ymin:.3f} ymax={bb.ymax:.3f} "
        f"zmin={bb.zmin:.3f} zmax={bb.zmax:.3f}"
    )

    # --- Find a near-axis cylinder close to the front to anchor the 'front center' feature ---
    cyl_cands = []
    for idx, f in enumerate(main_solid.Faces()):
        try:
            if str(f.geomType()).upper() != "CYLINDER":
                continue
        except Exception:
            continue

        fb = f.BoundingBox()
        fc = fb.center

        # Prefer axis ~Y cylinders (xlen ~ zlen)
        if abs(fb.xlen - fb.zlen) > 1.5:
            continue

        # Near axis
        radial_center = math.hypot(fc.x - xmid, fc.z - zmid)
        if radial_center > 3.0:
            continue

        # Near front
        y_to_front = y_front - fb.ymax
        if y_to_front > 3.0:
            continue

        r = 0.25 * (fb.xlen + fb.zlen)
        if r < 4.0 or r > 50.0:
            continue

        # Score: closer to front + larger radius
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

    # Among the closest-to-front candidates, choose the largest radius for stability
    top = cyl_cands[:8]
    _, ytf, r_target, face_idx, fb, fc = max(top, key=lambda t: t[2])
    cx, cz = fc.x, fc.z

    print(
        f"Selected target cylinder: faceIndex={face_idx}, r_target~{r_target:.3f}, "
        f"axisCenter=({cx:.3f},{cz:.3f}), face_y_to_front={ytf:.3f}"
    )

    # --- Metric: count torus (fillet) faces near the front and near this radius band ---
    def torus_near_front_count(solid, y_front_val, ax_cx, ax_cz, r_ref, y_band=2.0, r_band=2.0):
        c = 0
        for ff in solid.Faces():
            try:
                if str(ff.geomType()).upper() != "TORUS":
                    continue
            except Exception:
                continue
            fbb = ff.BoundingBox()
            if fbb.ymax < (y_front_val - y_band):
                continue
            corners = [
                (fbb.xmin, fbb.zmin), (fbb.xmin, fbb.zmax),
                (fbb.xmax, fbb.zmin), (fbb.xmax, fbb.zmax),
            ]
            rs = [math.hypot(x - ax_cx, z - ax_cz) for x, z in corners]
            rmin, rmax = min(rs), max(rs)
            if (r_ref >= (rmin - r_band)) and (r_ref <= (rmax + r_band)):
                c += 1
        return c

    torus_before = torus_near_front_count(main_solid, y_front, cx, cz, r_target)
    print(f"Torus-near-front metric BEFORE: {torus_before}")

    # --- Build two possible cutters: internal-hole chamfer vs external-boss chamfer ---
    chamfer = 1.0
    eps_y = 0.02
    eps_r = 0.02
    margin = 4.0

    # Apply at the front side only
    y0 = y_front - chamfer - eps_y
    y1 = y_front + eps_y
    dy = y1 - y0

    def wp_xz(yval):
        return cq.Workplane("XZ").workplane(offset=yval).center(cx, cz)

    # Internal hole chamfer: radius increases toward the front
    r_back_hole = max(0.1, r_target + eps_r)
    r_front_hole = max(0.1, r_target + chamfer + eps_r)
    hole_cutter = (
        wp_xz(y0)
        .circle(r_back_hole)
        .workplane(offset=dy)
        .circle(r_front_hole)
        .loft(combine=False, ruled=True)
    )

    # External boss chamfer: remove material outside the boss, leaving a taper to smaller radius at the front
    r_outer_boss = max(0.1, r_target + chamfer + margin)
    r_back_boss = max(0.1, r_target - eps_r)
    r_front_boss = max(0.1, r_target - chamfer - eps_r)
    boss_outer = wp_xz(y0).circle(r_outer_boss).extrude(dy)
    boss_inner_frustum = (
        wp_xz(y0)
        .circle(r_back_boss)
        .workplane(offset=dy)
        .circle(r_front_boss)
        .loft(combine=False, ruled=True)
    )
    boss_cutter = boss_outer.cut(boss_inner_frustum)

    orig_vol = main_solid.Volume()

    def try_cut(cutter, label):
        try:
            res = cq.Workplane(obj=main_solid).cut(cutter).val()
            try:
                valid = bool(res.isValid())
            except Exception:
                valid = True
            new_vol = res.Volume()
            removed = orig_vol - new_vol
            torus_after = torus_near_front_count(res, y_front, cx, cz, r_target)
            print(
                f"{label}: valid={valid} vol_removed={removed:.6f} "
                f"(orig={orig_vol:.6f} new={new_vol:.6f}) torusMetricAfter={torus_after}"
            )
            if (not valid) or (removed <= 1e-6):
                return None
            return {
                "label": label,
                "res": res,
                "removed": removed,
                "torus_after": torus_after,
            }
        except Exception as e:
            print(f"{label}: cut failed: {e}")
            return None

    hole_try = try_cut(hole_cutter, "HOLE_CHAMFER")
    boss_try = try_cut(boss_cutter, "BOSS_CHAMFER")

    if not hole_try and not boss_try:
        print("Neither chamfer cut produced a valid positive change; returning original")
        return model

    # Choose by: (1) greatest reduction of torus metric near front-center, then (2) minimal volume removal
    def score_choice(ch):
        if ch is None:
            return None
        torus_reduction = torus_before - ch["torus_after"]
        # higher better for reduction; smaller better for removal
        return (torus_reduction, -ch["removed"])

    choices = [c for c in (hole_try, boss_try) if c]
    # sort by torus_reduction desc, removed asc
    choices.sort(key=lambda c: (torus_before - c["torus_after"], -c["removed"]), reverse=True)
    chosen = choices[0]

    print(
        f"Chosen: {chosen['label']} (torusReduction={torus_before - chosen['torus_after']}, vol_removed={chosen['removed']:.6f})"
    )

    main_res = chosen["res"]

    # Recombine solids as a compound (avoid boolean-union of separate solids)
    if other_solids:
        final_shape = cq.Compound.makeCompound([main_res] + other_solids)
    else:
        final_shape = main_res

    print("Applied 1mm chamfer at the front center by replacing the fillet region via targeted cut.")
    return final_shape
