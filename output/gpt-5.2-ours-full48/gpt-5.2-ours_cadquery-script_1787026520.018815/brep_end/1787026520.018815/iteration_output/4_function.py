def my_cad_function(args):
    import cadquery as cq
    import os
    from math import isfinite

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

    # --- Find underside pocket shelf/floor face (planar, near-horizontal, internal, low Y) ---
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
            # exclude global bottom
            if abs(c.y - bottom_y) < 1e-7 * max_dim:
                continue
            # focus on lower region to find underside pocket floor/shelf
            if c.y > bottom_y + 0.65 * dy:
                continue
            cand.append((f.Area(), c.y, f, n, c))
        except Exception:
            continue

    if not cand:
        raise ValueError("Could not find a suitable planar internal face for pocket floor/shelf.")

    # Prefer large-area planar face slightly above bottom (often the pocket shelf)
    cand.sort(key=lambda t: (-t[0], t[1]))
    floor_area, floor_y, floor_face, floor_n, floor_c = cand[0]
    floor_bb = floor_face.BoundingBox()

    print("=== Chosen pocket shelf/floor face ===")
    print(f"floor_y={floor_y:.6f} area={floor_area:.6f} center=({floor_c.x:.6f},{floor_c.y:.6f},{floor_c.z:.6f})")
    print(f"floor_face_bb: x[{floor_bb.xmin:.6f},{floor_bb.xmax:.6f}] z[{floor_bb.zmin:.6f},{floor_bb.zmax:.6f}]")

    # --- Unit heuristic (choose model-units-per-mm scale) ---
    pocket_step = max(1e-9, floor_y - bb.ymin)
    scale_candidates = {
        "mm": 1.0,
        "cm": 0.1,
        "inch": 1.0 / 25.4,
        "m": 0.001,
    }

    def plausibility(scale):
        step_mm = pocket_step / scale
        # pocket shelf typically a few mm above bottom in many brackets
        if step_mm < 0.5 or step_mm > 50:
            p_step = 10.0
        else:
            p_step = abs(step_mm - 5.0) / 5.0
        return p_step

    best_unit = min(scale_candidates.keys(), key=lambda k: plausibility(scale_candidates[k]))
    mm_to_model = scale_candidates[best_unit]

    rib_t = 1.5 * mm_to_model
    eps = 0.05 * mm_to_model  # small overlap/robustness epsilon (~0.05mm)

    print("=== Unit heuristic ===")
    print(f"pocket_step(model)={pocket_step:.6f} -> inferred units='{best_unit}', mm_to_model={mm_to_model:.8f}")
    print(f"Requested rib thickness 1.5mm -> rib_t(model)={rib_t:.6f}")

    # Rib footprint: centered on the pocket shelf bounding box, long in X, thin in Z
    x_mid = 0.5 * (floor_bb.xmin + floor_bb.xmax)
    z_mid = 0.5 * (floor_bb.zmin + floor_bb.zmax)

    xspan = max(1e-9, (floor_bb.xmax - floor_bb.xmin))
    # keep rib inside pocket and away from end transitions
    x_margin = max(0.06 * xspan, 6.0 * rib_t)
    L = max(0.0, xspan - 2.0 * x_margin)
    if L < 20.0 * rib_t:
        L = max(20.0 * rib_t, 0.65 * xspan)

    print("=== Rib footprint ===")
    print(f"x_mid={x_mid:.6f}, z_mid={z_mid:.6f}, xspan={xspan:.6f}, x_margin={x_margin:.6f}, L={L:.6f}, rib_t={rib_t:.6f}")

    V0 = solid.Volume()
    print(f"Original volume: {V0:.6f}")

    def _largest_solid(shape):
        """Return the largest-volume Solid from a Shape (Solid/Compound)."""
        try:
            solids = shape.Solids()
            if solids and len(solids) > 0:
                best = None
                bestV = -1
                for s in solids:
                    try:
                        v = s.Volume()
                        if v > bestV:
                            bestV = v
                            best = s
                    except Exception:
                        continue
                if best is not None:
                    return best
        except Exception:
            pass
        return shape

    def try_candidate(y_sign):
        """Try to create a rib by extruding from the pocket shelf in +Y or -Y.

        Strategy:
          A) Preferred: extrude(until='next', combine=True) to stop at the next encountered face.
          B) Fallback: extrude long distance then keep only the portion in void using cut(solid),
             then translate slightly back into solid to guarantee boolean fusion.
        """
        if y_sign not in (+1, -1):
            raise ValueError("y_sign must be +1 or -1")

        normal = (0, 1, 0) if y_sign > 0 else (0, -1, 0)
        plane = cq.Plane(origin=(0, float(floor_y), 0), xDir=(1, 0, 0), normal=normal)

        # Sketch rectangle: long in X (plane x-axis), thickness in Z (plane y-axis ~ +/-Z)
        base = cq.Workplane(plane).center(float(x_mid), float(z_mid)).rect(float(L), float(rib_t), centered=True)

        # A) try 'until next'
        try:
            rib_wp = base.extrude(until="next", combine=True)
            rib_shape = rib_wp.val()
            rib_shape = _largest_solid(rib_shape)
            # ensure a tiny overlap into the parent solid (toward -normal)
            rib_shape = rib_shape.translate((0.0, float(-y_sign * eps), 0.0))
            res = solid.union(rib_shape)
            return res, {"mode": "until_next"}, None
        except Exception as e_until:
            # B) fallback: long extrude then subtract existing solid to keep only void-fill portion
            try:
                dist = max(1e-6, 2.0 * dy)
                prism_wp = base.extrude(float(dist))
                prism = prism_wp.val()
                prism = _largest_solid(prism)
                rib_void = prism.cut(solid)
                rib_void = _largest_solid(rib_void)

                # If cut removes everything, volume will be ~0
                try:
                    if rib_void.Volume() < 1e-9:
                        return None, None, f"fallback produced near-zero rib volume; until_next error was: {str(e_until)}"
                except Exception:
                    # If volume cannot be computed, still attempt but mark
                    pass

                # push slightly into solid for robust union
                rib_void = rib_void.translate((0.0, float(-y_sign * eps), 0.0))
                res = solid.union(rib_void)
                return res, {"mode": "long_extrude_cut", "until_next_error": str(e_until)}, None
            except Exception as e_fb:
                return None, None, f"until_next failed: {str(e_until)} | fallback failed: {str(e_fb)}"

    def eval_result(res):
        bb2 = res.BoundingBox()
        V2 = res.Volume()
        dV = V2 - V0
        deltas = {
            "dxmin": bb2.xmin - bb.xmin,
            "dxmax": bb2.xmax - bb.xmax,
            "dymin": bb2.ymin - bb.ymin,
            "dymax": bb2.ymax - bb.ymax,
            "dzmin": bb2.zmin - bb.zmin,
            "dzmax": bb2.zmax - bb.zmax,
        }
        bbox_pen = sum(abs(v) for v in deltas.values())
        frac = dV / max(1e-9, V0)
        # strong penalty if bbox changes materially (exterior breakthrough)
        score = bbox_pen * 1e6
        # must add material
        if dV <= 1e-9:
            score += 1e9
        # avoid absurd addition
        if frac > 0.08:
            score += (frac - 0.08) * 1e7
        # prefer single solid
        try:
            nsol = len(res.Solids())
            if nsol != 1:
                score += 1e6 * (nsol - 1)
        except Exception:
            pass
        return score, dV, frac, deltas

    candidates = []
    for sign, label in [(+1, "+Y"), (-1, "-Y")]:
        res, info, err = try_candidate(sign)
        if err:
            print(f"Candidate {label} failed: {err}")
            continue
        score, dV, frac, deltas = eval_result(res)
        print(f"Candidate {label} ok: mode={info['mode']} dV={dV:.6f} frac={frac:.6f} bbox_delta={deltas} score={score:.3f}")
        candidates.append((score, res, label, info))

    if not candidates:
        raise ValueError("All rib creation candidates failed; could not add rib.")

    candidates.sort(key=lambda t: t[0])
    best_score, best_res, best_label, best_info = candidates[0]
    print(f"=== Selected candidate: {best_label} (mode={best_info['mode']}) score={best_score:.3f} ===")

    # Final sanity: do not allow changes to the global bottom plane beyond tiny tolerance
    bbF = best_res.BoundingBox()
    if abs(bbF.ymin - bb.ymin) > 1e-6 * max_dim:
        print("WARNING: ymin changed; rib may have broken through to exterior. Trying next-best candidate if available.")
        if len(candidates) > 1:
            best_res = candidates[1][1]

    return best_res
