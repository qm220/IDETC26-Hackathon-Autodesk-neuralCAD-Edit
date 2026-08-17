def my_cad_function(args):
    import os
    import math
    import cadquery as cq

    if "input_file" not in args:
        print("No input_file provided")
        return None

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    occ = model.val() if hasattr(model, "val") else model

    print(f"Loaded STEP: {input_file}")
    print(f"Valid: {occ.isValid()}")

    solids = list(occ.Solids())
    print(f"Solids: {len(solids)}, Faces: {len(occ.Faces())}, Edges: {len(occ.Edges())}")
    if not solids:
        return model

    # Work on the largest solid (usually the main part)
    main_i, main_solid = max(enumerate(solids), key=lambda t: t[1].Volume())
    other_solids = [s for i, s in enumerate(solids) if i != main_i]

    bb = main_solid.BoundingBox()
    y_front = bb.ymax
    print(
        f"Main solid BBox: xmin={bb.xmin:.3f} xmax={bb.xmax:.3f} "
        f"ymin={bb.ymin:.3f} ymax={bb.ymax:.3f} "
        f"zmin={bb.zmin:.3f} zmax={bb.zmax:.3f}"
    )

    # --- Find a cylindrical hub surface near the model center and near the front ---
    # This is intended to target the front-center fillet around the hub outer diameter.
    xmid = 0.5 * (bb.xmin + bb.xmax)
    zmid = 0.5 * (bb.zmin + bb.zmax)

    cyl_cands = []
    for idx, f in enumerate(main_solid.Faces()):
        try:
            if str(f.geomType()).upper() != "CYLINDER":
                continue
        except Exception:
            continue

        fb = f.BoundingBox()
        fc = fb.center

        # Prefer cylinders whose axis is ~Y (bbox xlen ~ zlen)
        if abs(fb.xlen - fb.zlen) > 1.5:
            continue

        r = 0.25 * (fb.xlen + fb.zlen)
        if r < 6.0 or r > 35.0:
            continue

        # near center axis
        radial_center = math.hypot(fc.x - xmid, fc.z - zmid)
        if radial_center > 2.0:
            continue

        # near front
        y_to_front = y_front - fb.ymax
        if y_to_front > 2.0:
            continue

        # score: close to front, larger radius (outer hub) preferred
        score = 2.0 * y_to_front - 0.02 * r
        cyl_cands.append((score, r, fc.x, fc.z, fb.ymax, idx, fb))

    cyl_cands.sort(key=lambda t: t[0])
    print(f"Center/front CYLINDER candidates: {len(cyl_cands)}")
    for k, (score, r, cx, cz, fymax, idx, fb) in enumerate(cyl_cands[:10]):
        print(
            f"  cand[{k}] faceIndex={idx} score={score:.4f} r~{r:.3f} "
            f"axisCenter~({cx:.3f},{cz:.3f}) face_ymax={fymax:.3f} "
            f"bb=({fb.xlen:.3f},{fb.ylen:.3f},{fb.zlen:.3f})"
        )

    if not cyl_cands:
        print("No suitable center/front CYLINDER found; returning original.")
        return model

    # pick the largest radius among the best few (stabilizes against selecting small internal cylinders)
    best = cyl_cands[:6]
    score, r_target, cx, cz, cyl_ymax, face_idx, fb = max(best, key=lambda t: t[1])
    print(f"Selected hub cylinder: faceIndex={face_idx}, r_target~{r_target:.3f}, axisCenter=({cx:.3f},{cz:.3f})")

    # --- Create a 1mm chamfer by cutting a thin conical ring near the front ---
    chamfer = 1.0
    eps_y = 0.15
    eps_r = 0.03  # avoid coincident surfaces

    y0 = y_front - chamfer - eps_y
    y1 = y_front + eps_y
    dy = y1 - y0

    # Outer boundary slightly larger than hub radius; inner frustum defines remaining material.
    r_outer = r_target + eps_r
    r_back = max(0.1, r_target - eps_r)              # at y0 (deeper)
    r_front = max(0.1, r_target - chamfer - eps_r)   # at y1 (front)

    print(
        f"Chamfer cutter params: y0={y0:.3f} y1={y1:.3f} dy={dy:.3f} "
        f"r_outer={r_outer:.3f} r_back={r_back:.3f} r_front={r_front:.3f}"
    )

    wp0 = cq.Workplane("XZ").workplane(offset=y0).center(cx, cz)

    try:
        outer_cyl = wp0.circle(r_outer).extrude(dy)
        inner_frustum = (
            wp0.circle(r_back)
            .workplane(offset=dy)
            .circle(r_front)
            .loft(combine=False, ruled=True)
        )
        cutter = outer_cyl.cut(inner_frustum)

        main_res_wp = cq.Workplane(obj=main_solid).cut(cutter)
        main_res = main_res_wp.val()

        # Recombine solids as a compound (do not boolean-union separate solids)
        if other_solids:
            final_shape = cq.Compound.makeCompound([main_res] + other_solids)
        else:
            final_shape = main_res

        print("Applied 1mm front-center chamfer cut (replacing the fillet region).")
        return final_shape

    except Exception as e:
        print(f"Chamfer operation failed: {e}")
        return model
