def my_cad_function(args):
    import cadquery as cq
    import os

    # --- Load STEP ---
    if "input_file" not in args:
        raise ValueError("args['input_file'] not provided")
    step_path = os.path.expanduser(args["input_file"])
    model_wp = cq.importers.importStep(step_path)

    base_shape = model_wp.val() if hasattr(model_wp, "val") else model_wp
    if base_shape is None:
        raise ValueError("Failed to load STEP shape")

    print(f"Loaded STEP: {step_path}")
    print(f"Valid: {base_shape.isValid() if hasattr(base_shape, 'isValid') else 'unknown'}")

    solids = list(base_shape.Solids())
    print(f"Total solids in model: {len(solids)}")

    # --- Helper: bbox info ---
    def bb_info(s):
        bb = s.BoundingBox()
        return {
            "bb": bb,
            "cx": (bb.xmin + bb.xmax) / 2.0,
            "cy": (bb.ymin + bb.ymax) / 2.0,
            "cz": (bb.zmin + bb.zmax) / 2.0,
            "dx": (bb.xmax - bb.xmin),
            "dy": (bb.ymax - bb.ymin),
            "dz": (bb.zmax - bb.zmin),
        }

    # --- Find the existing horizontal pill button solid ---
    # Heuristics based on planning notes: small thin solid near the top control cluster.
    # Looking for: elongated in X, thin in Y, modest in Z, located roughly near dial cluster.
    candidates = []
    for i, s in enumerate(solids):
        info = bb_info(s)

        dx, dy, dz = info["dx"], info["dy"], info["dz"]
        cx, cy, cz = info["cx"], info["cy"], info["cz"]

        # Size/shape filters for a pill-ish button
        if not (12.0 <= dx <= 120.0):
            continue
        if not (1.0 <= dy <= 30.0):
            continue
        if not (2.0 <= dz <= 30.0):
            continue
        if dx / max(dz, 1e-6) < 1.6:
            continue

        # Location filters: near the top control area (avoid feet/vent patterns)
        if not (200.0 <= cy <= 380.0):
            continue
        if not (260.0 <= cz <= 340.0):
            continue

        # Prefer left-of-center near x ~ -150..-250 (button "left of dial")
        if not (-260.0 <= cx <= -120.0):
            continue

        # Score: prefer longer in X and thinner in Y; small penalty for being far from expected dial z
        score = (dx * 2.0) - (dy * 4.0) - abs(cz - 316.0) * 0.5
        candidates.append((score, i, s, info))

    # Debug print top candidates
    candidates_sorted = sorted(candidates, key=lambda t: t[0], reverse=True)
    print(f"Button candidates found: {len(candidates_sorted)}")
    for rank, (score, i, _s, info) in enumerate(candidates_sorted[:10]):
        print(
            f"  cand[{rank}] solid_idx={i} score={score:.2f} مرکز=({info['cx']:.2f},{info['cy']:.2f},{info['cz']:.2f}) "
            f"dims(dx,dy,dz)=({info['dx']:.2f},{info['dy']:.2f},{info['dz']:.2f})"
        )

    if not candidates_sorted:
        raise ValueError(
            "Could not automatically identify the existing horizontal button solid. "
            "Heuristics found no candidates; adjust filters after reviewing printed solid bboxes."
        )

    # Pick best candidate
    _, btn_idx, btn_solid, btn_info = candidates_sorted[0]
    print(
        f"Selected button solid idx={btn_idx} center=({btn_info['cx']:.2f},{btn_info['cy']:.2f},{btn_info['cz']:.2f}) "
        f"dims=({btn_info['dx']:.2f},{btn_info['dy']:.2f},{btn_info['dz']:.2f})"
    )

    # --- Define equal spacing pitch (Z direction) ---
    # Use button height and a small gap heuristic.
    pitch = max(12.0, 2.0 * btn_info["dz"] + 6.0)
    print(f"Using vertical pitch (center-to-center) = {pitch:.2f} mm")

    # Copy above/below
    try:
        btn_top = btn_solid.copy().translate((0, 0, +pitch))
        btn_bot = btn_solid.copy().translate((0, 0, -pitch))
    except Exception:
        # Fallback if .copy() not available
        btn_top = btn_solid.translate((0, 0, +pitch))
        btn_bot = btn_solid.translate((0, 0, -pitch))

    # --- Return as multi-solid compound (do not fuse/union) ---
    new_solids = solids + [btn_top, btn_bot]
    result = cq.Compound.makeCompound(new_solids)

    # Basic sanity
    bb_res = result.BoundingBox()
    print(
        f"Result bbox: x[{bb_res.xmin:.2f},{bb_res.xmax:.2f}] y[{bb_res.ymin:.2f},{bb_res.ymax:.2f}] z[{bb_res.zmin:.2f},{bb_res.zmax:.2f}]"
    )

    return result
