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

    # Work on the largest solid
    main_i, main_solid = max(enumerate(solids), key=lambda t: t[1].Volume())
    other_solids = [s for i, s in enumerate(solids) if i != main_i]

    bb = main_solid.BoundingBox()
    xmid = 0.5 * (bb.xmin + bb.xmax)
    zmid = 0.5 * (bb.zmin + bb.zmax)
    y_front = bb.ymax
    print(
        f"Main solid BBox: xmin={bb.xmin:.3f} xmax={bb.xmax:.3f} "
        f"ymin={bb.ymin:.3f} ymax={bb.ymax:.3f} "
        f"zmin={bb.zmin:.3f} zmax={bb.zmax:.3f}"
    )

    # --- Find a near-axis cylindrical face close to the front ---
    cyl_cands = []
    for idx, f in enumerate(main_solid.Faces()):
        try:
            if str(f.geomType()).upper() != "CYLINDER":
                continue
        except Exception:
            continue

        fb = f.BoundingBox()
        fc = fb.center

        # prefer axis ~Y (xlen ~ zlen)
        if abs(fb.xlen - fb.zlen) > 1.5:
            continue

        # near axis
        radial_center = math.hypot(fc.x - xmid, fc.z - zmid)
        if radial_center > 2.0:
            continue

        # near front
        y_to_front = y_front - fb.ymax
        if y_to_front > 2.5:
            continue

        r = 0.25 * (fb.xlen + fb.zlen)
        if r < 4.0 or r > 40.0:
            continue

        # prefer larger radius and closer to front
        score = 2.0 * y_to_front + 0.05 * radial_center - 0.02 * r
        cyl_cands.append((score, r, idx, fb, fc))

    cyl_cands.sort(key=lambda t: t[0])
    print(f"Center/front CYLINDER candidates: {len(cyl_cands)}")
    for k, (score, r, idx, fb, fc) in enumerate(cyl_cands[:10]):
        print(
            f"  cand[{k}] faceIndex={idx} score={score:.4f} r~{r:.3f} "
            f"ymax={fb.ymax:.3f} y_to_front={y_front - fb.ymax:.3f} "
            f"bb=({fb.xlen:.3f},{fb.ylen:.3f},{fb.zlen:.3f}) center=({fc.x:.3f},{fc.y:.3f},{fc.z:.3f})"
        )

    if not cyl_cands:
        print("No suitable center/front CYLINDER found; returning original.")
        return model

    # stabilize: choose the largest radius among top few
    top = cyl_cands[:6]
    _, r_target, face_idx, fb, fc = max(top, key=lambda t: t[1])
    cx, cz = fc.x, fc.z
    yb0, yb1 = fb.ymin, fb.ymax

    print(
        f"Selected hub cylinder: faceIndex={face_idx}, r_target~{r_target:.3f}, "
        f"axisCenter=({cx:.3f},{cz:.3f}), cyl_y=[{yb0:.3f},{yb1:.3f}]"
    )

    # --- Decide if the cylinder is a HOLE (internal) or a BOSS (external) ---
    # Use point-in-solid tests at a Y where the cylinder exists.
    y_test = 0.5 * (yb0 + yb1)
    d = 0.6
    tol = 1e-3

    def _is_inside(vec):
        try:
            return bool(main_solid.isInside(vec, tol))
        except Exception:
            # fallback: if isInside not available, assume boss
            return None

    pin = cq.Vector(cx + max(0.1, r_target - d), y_test, cz)   # slightly inside radius
    pout = cq.Vector(cx + (r_target + d), y_test, cz)          # slightly outside radius

    inside_in = _is_inside(pin)
    inside_out = _is_inside(pout)

    # Heuristic:
    # - For a hole: point just inside radius tends to be NOT inside (void), point just outside tends to be inside (solid).
    # - For a boss: point just inside radius tends to be inside (solid), point just outside tends to be NOT inside (air) at this y.
    is_hole = False
    if inside_in is not None and inside_out is not None:
        if (inside_in is False) and (inside_out is True):
            is_hole = True
        elif (inside_in is True) and (inside_out is False):
            is_hole = False
        else:
            # ambiguous: default to boss for this sprocket-like part
            is_hole = False

    print(f"Point-in-solid test at y={y_test:.3f}: inside(r-d)={inside_in}, inside(r+d)={inside_out} -> treating as {'HOLE' if is_hole else 'BOSS'}")

    # --- Build cutter to replace the front fillet with a 1mm chamfer ---
    chamfer = 1.0
    eps_y = 0.05
    eps_r = 0.03

    y0 = y_front - chamfer - eps_y
    y1 = y_front + eps_y
    dy = y1 - y0

    def _wp_xz(yval):
        return cq.Workplane("XZ").workplane(offset=yval).center(cx, cz)

    try:
        if is_hole:
            # Internal chamfer: increase radius toward the front
            r_back = max(0.1, r_target + eps_r)
            r_front = max(0.1, r_target + chamfer + eps_r)
            frustum = _wp_xz(y0).circle(r_back).workplane(offset=dy).circle(r_front).loft(combine=False, ruled=True)
            inner = _wp_xz(y0).circle(max(0.05, r_target - eps_r)).extrude(dy)
            cutter = frustum.cut(inner)
            print(
                f"Chamfer cutter (HOLE): y0={y0:.3f} y1={y1:.3f} dy={dy:.3f} "
                f"r_back={r_back:.3f} r_front={r_front:.3f}"
            )
        else:
            # External chamfer on a boss: reduce radius toward the front
            r_outer = r_target + 0.6
            r_back = max(0.1, r_target - eps_r)
            r_front = max(0.1, r_target - chamfer - eps_r)
            outer_cyl = _wp_xz(y0).circle(r_outer).extrude(dy)
            inner_frustum = _wp_xz(y0).circle(r_back).workplane(offset=dy).circle(r_front).loft(combine=False, ruled=True)
            cutter = outer_cyl.cut(inner_frustum)
            print(
                f"Chamfer cutter (BOSS): y0={y0:.3f} y1={y1:.3f} dy={dy:.3f} "
                f"r_outer={r_outer:.3f} r_back={r_back:.3f} r_front={r_front:.3f}"
            )

        main_res = cq.Workplane(obj=main_solid).cut(cutter).val()

        if other_solids:
            final_shape = cq.Compound.makeCompound([main_res] + other_solids)
        else:
            final_shape = main_res

        print("Applied 1mm chamfer at the front-center region (cut-based replacement of fillet).")
        return final_shape

    except Exception as e:
        print(f"Chamfer replacement cut failed: {e}")
        return model
