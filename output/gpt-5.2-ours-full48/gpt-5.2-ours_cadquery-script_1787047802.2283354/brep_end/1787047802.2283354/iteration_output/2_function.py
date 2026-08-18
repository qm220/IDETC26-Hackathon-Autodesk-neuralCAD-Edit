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
    try:
        print(f"Valid: {base_shape.isValid()}")
    except Exception:
        print("Valid: unknown")

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

    # --- Find existing horizontal pill button solid ---
    # Keep heuristic search but do not assume which axis is vertical; we'll infer later.
    candidates = []
    for i, s in enumerate(solids):
        info = bb_info(s)
        dx, dy, dz = info["dx"], info["dy"], info["dz"]
        cx, cy, cz = info["cx"], info["cy"], info["cz"]

        dims = sorted([dx, dy, dz])
        dmin, dmid, dmax = dims[0], dims[1], dims[2]

        # pill-like: one long axis, one medium axis, one thin axis
        if not (12.0 <= dmax <= 130.0):
            continue
        if not (4.0 <= dmid <= 25.0):
            continue
        if not (1.0 <= dmin <= 8.0):
            continue
        if dmax / max(dmid, 1e-6) < 1.6:
            continue

        # Location filters around the top control area (works for this model)
        if not (-290.0 <= cx <= -90.0):
            continue
        if not (200.0 <= cy <= 390.0):
            continue
        if not (250.0 <= cz <= 360.0):
            continue

        # Prefer: long in X, thin in (Y or Z) and close to previous observed center
        # (Observed prior run: center ~ (-237, 340, 318.5), dims ~ (43,10,4.8))
        score = (
            (dx * 2.5) +
            (1.0 / max(min(dy, dz), 1e-6)) * 5.0 -
            abs(cx + 237.0) * 0.05 -
            abs(cy - 340.0) * 0.05 -
            abs(cz - 318.5) * 0.05
        )
        candidates.append((score, i, s, info))

    candidates_sorted = sorted(candidates, key=lambda t: t[0], reverse=True)
    print(f"Button candidates found: {len(candidates_sorted)}")
    for rank, (score, i, _s, info) in enumerate(candidates_sorted[:10]):
        print(
            f"  cand[{rank}] solid_idx={i} score={score:.2f} center=({info['cx']:.2f},{info['cy']:.2f},{info['cz']:.2f}) "
            f"dims(dx,dy,dz)=({info['dx']:.2f},{info['dy']:.2f},{info['dz']:.2f})"
        )

    if not candidates_sorted:
        raise ValueError(
            "Could not automatically identify the existing horizontal button solid. "
            "No pill-like small solid candidates found; adjust filters based on printed solid bboxes."
        )

    _, btn_idx, btn_solid, btn_info = candidates_sorted[0]
    print(
        f"Selected button solid idx={btn_idx} center=({btn_info['cx']:.2f},{btn_info['cy']:.2f},{btn_info['cz']:.2f}) "
        f"dims(dx,dy,dz)=({btn_info['dx']:.2f},{btn_info['dy']:.2f},{btn_info['dz']:.2f})"
    )

    # --- Infer translation axis for 'above/below' ---
    # We infer: long axis = max dimension, normal (panel thickness) = min dimension,
    # vertical axis = remaining axis.
    dims = {"X": btn_info["dx"], "Y": btn_info["dy"], "Z": btn_info["dz"]}
    long_axis = max(dims, key=dims.get)
    normal_axis = min(dims, key=dims.get)
    vertical_axis = [a for a in ("X", "Y", "Z") if a not in (long_axis, normal_axis)][0]

    # Pitch = size along vertical axis + gap
    gap = 6.0
    pitch = max(12.0, dims[vertical_axis] + gap)

    print(f"Inferred axes: long_axis={long_axis}, normal_axis={normal_axis}, vertical_axis(for above/below)={vertical_axis}")
    print(f"Using pitch (center-to-center) = {pitch:.2f} mm")

    def vec_for_axis(axis, amount):
        if axis == "X":
            return cq.Vector(amount, 0, 0)
        if axis == "Y":
            return cq.Vector(0, amount, 0)
        return cq.Vector(0, 0, amount)

    v_up = vec_for_axis(vertical_axis, +pitch)
    v_dn = vec_for_axis(vertical_axis, -pitch)

    # Use moved(Location) to avoid in-place mutation issues
    btn_top = btn_solid.moved(cq.Location(v_up))
    btn_bot = btn_solid.moved(cq.Location(v_dn))

    # --- Return as multi-solid compound (do not fuse/union) ---
    new_solids = solids + [btn_top, btn_bot]
    result = cq.Compound.makeCompound(new_solids)

    bb_res = result.BoundingBox()
    print(
        f"Result bbox: x[{bb_res.xmin:.2f},{bb_res.xmax:.2f}] "
        f"y[{bb_res.ymin:.2f},{bb_res.ymax:.2f}] z[{bb_res.zmin:.2f},{bb_res.zmax:.2f}]"
    )

    return result
