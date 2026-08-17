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

    # Work on largest solid (main part)
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

    chamfer = 1.0  # mm

    # --- Find near-axis CYLINDER face close to the front (front-center feature anchor) ---
    cyl_cands = []
    for idx, f in enumerate(main_solid.Faces()):
        try:
            if str(f.geomType()).upper() != "CYLINDER":
                continue
        except Exception:
            continue

        fb = f.BoundingBox()
        fc = fb.center

        # Axis ~Y => xlen ~ zlen
        if abs(fb.xlen - fb.zlen) > 1.5:
            continue

        # close to model axis
        radial_center = math.hypot(fc.x - xmid, fc.z - zmid)
        if radial_center > 3.0:
            continue

        # close to front
        y_to_front = y_front - fb.ymax
        if y_to_front > 3.0:
            continue

        r = 0.25 * (fb.xlen + fb.zlen)
        if r < 4.0 or r > 60.0:
            continue

        # Score: prioritize front proximity, then larger radius
        score = 5.0 * y_to_front - 0.03 * r + 0.1 * radial_center
        cyl_cands.append((score, y_to_front, r, idx, fb, fc))

    cyl_cands.sort(key=lambda t: t[0])
    print(f"Front/axis CYLINDER candidates: {len(cyl_cands)}")
    for k, (score, ytf, r, idx, fb, fc) in enumerate(cyl_cands[:8]):
        print(
            f"  cand[{k}] faceIndex={idx} score={score:.4f} y_to_front={ytf:.3f} r~{r:.3f} "
            f"y=[{fb.ymin:.3f},{fb.ymax:.3f}] center=({fc.x:.3f},{fc.y:.3f},{fc.z:.3f})"
        )

    if not cyl_cands:
        print("No suitable front/axis CYLINDER found; returning original")
        return model

    # Choose stable target: among closest-to-front few, pick the largest radius
    top = cyl_cands[:10]
    _, ytf, r_target, face_idx, fb, fc = max(top, key=lambda t: t[2])
    cx, cz = fc.x, fc.z

    print(
        f"Selected target cylinder: faceIndex={face_idx}, r_target~{r_target:.3f}, "
        f"axisCenter=({cx:.3f},{cz:.3f}), face_y_to_front={ytf:.3f}"
    )

    # --- Decide hole vs boss using point-in-solid tests ---
    y_test = max(fb.ymin + 0.2, min(fb.ymax - 0.2, 0.5 * (fb.ymin + fb.ymax)))

    def safe_is_inside(v):
        try:
            return bool(main_solid.isInside(v, 1e-3))
        except Exception:
            return None

    # sample well inside radius and well outside radius
    p_inside_r = cq.Vector(cx + max(0.1, 0.5 * r_target), y_test, cz)
    p_outside_r = cq.Vector(cx + (r_target + 0.8), y_test, cz)
    inside_in = safe_is_inside(p_inside_r)
    inside_out = safe_is_inside(p_outside_r)

    # For a HOLE: inside at half-radius tends to be False (void), outside radius tends to be True (solid)
    is_hole = False
    if inside_in is not None and inside_out is not None:
        if (inside_in is False) and (inside_out is True):
            is_hole = True
        elif (inside_in is True) and (inside_out is False):
            is_hole = False
        else:
            # ambiguous; default to HOLE for "front center" request
            is_hole = True
    else:
        is_hole = True

    print(f"Point-in-solid: inside(0.5r)={inside_in}, inside(r+0.8)={inside_out} -> treating as {'HOLE' if is_hole else 'BOSS'}")

    # --- Build cutter to create a 1mm chamfer at the front center ---
    # Use a small epsilon to avoid coincident faces.
    eps_y = 0.05
    eps_r = 0.02

    y0 = y_front - chamfer - eps_y
    y1 = y_front + eps_y
    dy = y1 - y0

    def wp_xz(yval):
        return cq.Workplane("XZ").workplane(offset=yval).center(cx, cz)

    try:
        if is_hole:
            # Hole entrance chamfer: radius increases toward the front
            r_back = max(0.1, r_target + eps_r)
            r_front = max(0.1, r_target + chamfer + eps_r)
            cutter = (
                wp_xz(y0)
                .circle(r_back)
                .workplane(offset=dy)
                .circle(r_front)
                .loft(combine=False, ruled=True)
            )
            print(f"Cutting HOLE chamfer frustum: y0={y0:.3f} y1={y1:.3f} r_back={r_back:.3f} r_front={r_front:.3f}")
        else:
            # Boss chamfer: remove material around outside of boss, leaving smaller radius at front
            r_outer = r_target + chamfer + 6.0
            r_back = max(0.1, r_target - eps_r)
            r_front = max(0.1, r_target - chamfer - eps_r)
            outer_cyl = wp_xz(y0).circle(r_outer).extrude(dy)
            inner_frustum = (
                wp_xz(y0)
                .circle(r_back)
                .workplane(offset=dy)
                .circle(r_front)
                .loft(combine=False, ruled=True)
            )
            cutter = outer_cyl.cut(inner_frustum)
            print(
                f"Cutting BOSS chamfer ring: y0={y0:.3f} y1={y1:.3f} r_outer={r_outer:.3f} r_back={r_back:.3f} r_front={r_front:.3f}"
            )

        orig_vol = main_solid.Volume()
        main_res = cq.Workplane(obj=main_solid).cut(cutter).val()
        new_vol = main_res.Volume()
        print(f"Volume removed (main solid): {orig_vol - new_vol:.6f} mm^3")

        # Recombine solids as a compound (keep separate solids separate)
        if other_solids:
            final_shape = cq.Compound.makeCompound([main_res] + other_solids)
        else:
            final_shape = main_res

        print("Applied 1mm chamfer at the front center (cut-based replacement of fillet).")
        return final_shape

    except Exception as e:
        print(f"Chamfer cut failed: {e}")
        return model
