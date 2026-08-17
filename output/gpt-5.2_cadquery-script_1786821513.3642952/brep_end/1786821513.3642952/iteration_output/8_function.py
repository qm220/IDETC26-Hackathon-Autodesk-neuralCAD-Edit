def my_cad_function(args):
    import os
    import math
    import cadquery as cq

    if "input_file" not in args:
        print("No input_file provided")
        return None

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shp = model.val() if hasattr(model, "val") else model

    solids = list(shp.Solids())
    print(f"Loaded STEP: {input_file}")
    try:
        print(f"Valid: {shp.isValid()}")
    except Exception:
        pass
    print(f"Solids: {len(solids)}, Faces: {len(shp.Faces())}, Edges: {len(shp.Edges())}")
    if not solids:
        return model

    # Work on largest solid; keep others unchanged
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

    # --- Find the front-center cylindrical face (axis ~Y, near model axis, near front) ---
    cyl_cands = []
    for idx, f in enumerate(main_solid.Faces()):
        try:
            if str(f.geomType()).upper() != "CYLINDER":
                continue
        except Exception:
            continue

        fb = f.BoundingBox()
        fc = fb.center

        # axis ~Y => xlen ~ zlen
        if abs(fb.xlen - fb.zlen) > 1.5:
            continue

        # near global axis
        radial_center = math.hypot(fc.x - xmid, fc.z - zmid)
        if radial_center > 3.0:
            continue

        # near the front
        y_to_front = y_front - fb.ymax
        if y_to_front > 3.0:
            continue

        r = 0.25 * (fb.xlen + fb.zlen)
        if r < 4.0 or r > 80.0:
            continue

        # prioritize close-to-front; prefer a substantial radius (likely counterbore at center)
        score = 6.0 * y_to_front + 0.10 * radial_center - 0.02 * r
        cyl_cands.append((score, y_to_front, r, idx, fb, fc))

    cyl_cands.sort(key=lambda t: t[0])
    print(f"Front/axis CYLINDER candidates: {len(cyl_cands)}")
    for k, (score, ytf, r, idx, fb, fc) in enumerate(cyl_cands[:8]):
        print(
            f"  cand[{k}] faceIndex={idx} score={score:.4f} y_to_front={ytf:.3f} r~{r:.3f} "
            f"y=[{fb.ymin:.3f},{fb.ymax:.3f}] center=({fc.x:.3f},{fc.y:.3f},{fc.z:.3f})"
        )

    if not cyl_cands:
        print("No suitable front-center cylinder found; returning original model")
        return model

    # among the top few (front-most), pick largest radius for stability
    top = cyl_cands[:10]
    _, ytf, r_target, face_idx, fb, fc = max(top, key=lambda t: t[2])
    cx, cz = fc.x, fc.z

    print(
        f"Selected target cylinder: faceIndex={face_idx}, r_target~{r_target:.3f}, "
        f"axisCenter=({cx:.3f},{cz:.3f}), face_y_to_front={ytf:.3f}"
    )

    # Decide if this cylinder bounds a hole (void inside, solid outside)
    y_test = max(fb.ymin + 0.2, min(fb.ymax - 0.2, 0.5 * (fb.ymin + fb.ymax)))

    def safe_is_inside(v):
        try:
            return bool(main_solid.isInside(v, 1e-3))
        except Exception:
            return None

    inside_half = safe_is_inside(cq.Vector(cx + 0.5 * r_target, y_test, cz))
    outside = safe_is_inside(cq.Vector(cx + (r_target + 0.8), y_test, cz))
    is_hole = True
    if inside_half is not None and outside is not None:
        is_hole = (inside_half is False) and (outside is True)

    print(f"Point-in-solid: inside(0.5r)={inside_half}, inside(r+0.8)={outside} -> treating as {'HOLE' if is_hole else 'BOSS'}")

    # --- Replace the front-center fillet with a 1mm chamfer (45-deg) via a targeted cut ---
    chamfer = 1.0
    eps_y = 0.03
    eps_r = 0.02

    # Apply only near the front
    y0 = y_front - chamfer - eps_y
    y1 = y_front + eps_y
    dy = y1 - y0

    def wp_xz(yval):
        return cq.Workplane("XZ").workplane(offset=yval).center(cx, cz)

    try:
        if is_hole:
            # Hole entrance chamfer: radius increases toward the front by 1mm over 1mm
            r_back = max(0.1, r_target + eps_r)
            r_front = max(0.1, r_target + chamfer + eps_r)

            # Make it an annular cutter to avoid touching anything far from the boundary
            inner_r = max(0.1, r_target - 0.5)
            frustum = (
                wp_xz(y0)
                .circle(r_back)
                .workplane(offset=dy)
                .circle(r_front)
                .loft(combine=False, ruled=True)
            )
            inner = wp_xz(y0).circle(inner_r).extrude(dy)
            cutter = frustum.cut(inner)

            print(f"Cutting HOLE chamfer: y0={y0:.3f} y1={y1:.3f} r_back={r_back:.3f} r_front={r_front:.3f} inner_r={inner_r:.3f}")
        else:
            # Boss edge chamfer (fallback): radius decreases toward the front by 1mm over 1mm
            r_outer = r_target + chamfer + 6.0
            r_back = max(0.1, r_target + eps_r)
            r_front = max(0.1, r_target - chamfer - eps_r)

            outer = wp_xz(y0).circle(r_outer).extrude(dy)
            keep = (
                wp_xz(y0)
                .circle(r_back)
                .workplane(offset=dy)
                .circle(r_front)
                .loft(combine=False, ruled=True)
            )
            cutter = outer.cut(keep)

            print(f"Cutting BOSS chamfer: y0={y0:.3f} y1={y1:.3f} r_back={r_back:.3f} r_front={r_front:.3f} r_outer={r_outer:.3f}")

        orig_vol = main_solid.Volume()
        main_res = cq.Workplane(obj=main_solid).cut(cutter).val()
        new_vol = main_res.Volume()
        print(f"Volume removed (main solid): {orig_vol - new_vol:.6f} mm^3")

        if other_solids:
            return cq.Compound.makeCompound([main_res] + other_solids)
        return main_res

    except Exception as e:
        print(f"Chamfer replacement cut failed: {e}")
        return model
