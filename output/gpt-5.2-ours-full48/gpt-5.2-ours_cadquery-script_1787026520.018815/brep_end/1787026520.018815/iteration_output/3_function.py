def my_cad_function(args):
    import cadquery as cq
    import os

    input_file = args.get("input_file", None)
    if not input_file:
        raise ValueError("args['input_file'] is required")
    input_file = os.path.expanduser(input_file)
    if not os.path.exists(input_file):
        raise ValueError(f"Missing STEP file: {input_file}")

    wp = cq.importers.importStep(input_file)
    solid = wp.val() if hasattr(wp, "val") else wp

    bb = solid.BoundingBox()
    dx, dy, dz = (bb.xmax - bb.xmin), (bb.ymax - bb.ymin), (bb.zmax - bb.zmin)
    max_dim = max(dx, dy, dz)

    print("=== Loaded model ===")
    print(f"BBox: x[{bb.xmin:.6f},{bb.xmax:.6f}] y[{bb.ymin:.6f},{bb.ymax:.6f}] z[{bb.zmin:.6f},{bb.zmax:.6f}]")
    print(f"Dims: dx={dx:.6f}, dy={dy:.6f}, dz={dz:.6f}, max_dim={max_dim:.6f}")

    # --- Find candidate internal pocket shelf/floor faces (near-horizontal planar, above global bottom) ---
    faces = solid.Faces()
    bottom_y = bb.ymin

    cand = []
    for f in faces:
        try:
            if f.geomType() != "PLANE":
                continue
            n = f.normalAt()
            if abs(n.y) < 0.95:
                continue
            c = f.Center()
            # exclude the global bottom face itself
            if abs(c.y - bottom_y) < 1e-6 * max_dim:
                continue
            # focus on underside pocket region: within lower 50% of height
            if c.y > bottom_y + 0.55 * dy:
                continue
            cand.append((f.Area(), c.y, f, n, c))
        except Exception:
            continue

    if not cand:
        raise ValueError("Could not find a suitable horizontal internal face for pocket floor/shelf.")

    # Choose the largest-area candidate in the lower region (tends to be the pocket shelf)
    cand.sort(key=lambda t: (-t[0], t[1]))
    floor_area, floor_y, floor_face, floor_n, floor_c = cand[0]
    floor_bb = floor_face.BoundingBox()

    print("=== Chosen pocket shelf/floor face ===")
    print(f"floor_y={floor_y:.6f} area={floor_area:.6f} center=({floor_c.x:.6f},{floor_c.y:.6f},{floor_c.z:.6f})")
    print(f"floor_face_bb: x[{floor_bb.xmin:.6f},{floor_bb.xmax:.6f}] z[{floor_bb.zmin:.6f},{floor_bb.zmax:.6f}]")

    # --- Unit/scale heuristic ---
    # Try to infer whether model units are mm, cm, or inch based on typical pocket step height.
    pocket_step = max(1e-9, floor_y - bb.ymin)
    # Candidate scales: model_unit_per_mm
    scale_candidates = {
        "mm": 1.0,
        "cm": 0.1,
        "inch": 1.0 / 25.4,
        "m": 0.001,
    }

    # Prefer a scale that makes the pocket step (floor_y - ymin) land in a plausible mm range
    # (roughly 2mm..20mm for an underside shelf/step), and keeps a 1.5mm rib reasonably thin.
    def plausibility(scale):
        step_mm = pocket_step / scale
        rib_t_model = 1.5 * scale
        # penalty for implausible step size
        if step_mm < 0.5 or step_mm > 50:
            p_step = 10.0
        else:
            # closer to ~5mm is common
            p_step = abs(step_mm - 5.0) / 5.0
        # penalty if rib is too thick relative to pocket width
        zspan = max(1e-9, floor_bb.zmax - floor_bb.zmin)
        ratio = rib_t_model / zspan
        p_ratio = 0.0
        if ratio > 0.2:
            p_ratio = (ratio - 0.2) * 10.0
        return p_step + p_ratio

    best_unit = min(scale_candidates.keys(), key=lambda k: plausibility(scale_candidates[k]))
    mm_to_model = scale_candidates[best_unit]

    rib_t = 1.5 * mm_to_model

    print("=== Unit heuristic ===")
    print(f"pocket_step(model)={pocket_step:.6f} -> inferred units='{best_unit}', mm_to_model={mm_to_model:.8f}")
    print(f"Requested rib thickness 1.5mm -> rib_t(model)={rib_t:.6f}")

    # Rib footprint on the chosen shelf: centered in pocket, running along global X
    x_mid = 0.5 * (floor_bb.xmin + floor_bb.xmax)
    z_mid = 0.5 * (floor_bb.zmin + floor_bb.zmax)

    xspan = max(1e-9, (floor_bb.xmax - floor_bb.xmin))
    # Keep margins to avoid end transitions; based on span and rib thickness
    x_margin = max(0.05 * xspan, 6.0 * rib_t)
    L = max(0.0, xspan - 2.0 * x_margin)
    if L < 20.0 * rib_t:
        # ensure not degenerate
        L = max(20.0 * rib_t, 0.6 * xspan)

    print("=== Rib footprint ===")
    print(f"x_mid={x_mid:.6f}, z_mid={z_mid:.6f}, xspan={xspan:.6f}, x_margin={x_margin:.6f}, L={L:.6f}, rib_t={rib_t:.6f}")

    # Build two candidates: extrude in +Y and in -Y, then choose the one that:
    # - does not change the global bounding box (no exterior breakthrough)
    # - actually increases volume (adds material)
    V0 = solid.Volume()
    print(f"Original volume: {V0:.6f}")

    def try_candidate(y_sign):
        """y_sign=+1 extrude along +Y, y_sign=-1 along -Y"""
        normal = (0, 1, 0) if y_sign > 0 else (0, -1, 0)
        plane = cq.Plane(origin=(0, float(floor_y), 0), xDir=(1, 0, 0), normal=normal)
        try:
            rib_wp = cq.Workplane(plane).center(float(x_mid), float(z_mid)).rect(float(L), float(rib_t), centered=True)
            rib = rib_wp.extrude(until="next", combine=False).val()
            res = solid.union(rib)
            return res, None
        except Exception as e:
            return None, str(e)

    res_p, err_p = try_candidate(+1)
    res_m, err_m = try_candidate(-1)

    if err_p:
        print(f"Candidate +Y failed: {err_p}")
    if err_m:
        print(f"Candidate -Y failed: {err_m}")

    def eval_result(res):
        bb2 = res.BoundingBox()
        V2 = res.Volume()
        dV = V2 - V0
        # bounding box changes (should be ~0 if internal)
        d = {
            "dxmin": bb2.xmin - bb.xmin,
            "dxmax": bb2.xmax - bb.xmax,
            "dymin": bb2.ymin - bb.ymin,
            "dymax": bb2.ymax - bb.ymax,
            "dzmin": bb2.zmin - bb.zmin,
            "dzmax": bb2.zmax - bb.zmax,
        }
        # score: prefer minimal bbox change, positive moderate volume gain
        bbox_pen = sum(abs(v) for v in d.values())
        # penalize no-op
        noop_pen = 0.0 if dV > 1e-9 else 1e6
        # penalize massive addition (usually indicates unit mistake or breakout)
        frac = dV / max(1e-9, V0)
        big_pen = 0.0 if frac < 0.05 else (frac - 0.05) * 1e4
        score = bbox_pen * 1e3 + noop_pen + big_pen
        return score, dV, frac, d

    candidates = []
    if res_p is not None:
        score, dV, frac, d = eval_result(res_p)
        print(f"+Y: dV={dV:.6f} frac={frac:.6f} bbox_delta={d} score={score:.3f}")
        candidates.append((score, res_p, "+Y"))
    if res_m is not None:
        score, dV, frac, d = eval_result(res_m)
        print(f"-Y: dV={dV:.6f} frac={frac:.6f} bbox_delta={d} score={score:.3f}")
        candidates.append((score, res_m, "-Y"))

    if not candidates:
        raise ValueError("Both rib candidates failed; cannot create rib with until='next'.")

    candidates.sort(key=lambda t: t[0])
    best = candidates[0]
    print(f"=== Selected candidate direction: {best[2]} ===")

    return best[1]
