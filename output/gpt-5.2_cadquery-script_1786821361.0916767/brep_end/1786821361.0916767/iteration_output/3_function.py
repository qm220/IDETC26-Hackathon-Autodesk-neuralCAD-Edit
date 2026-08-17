def my_cad_function(args):
    import os, math
    import cadquery as cq

    if "input_file" not in args:
        print("No input_file provided.")
        return None

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    base = model.val() if hasattr(model, "val") else model

    print(f"Loaded STEP: {input_file}")
    try:
        print(f"Is Valid: {base.isValid()}")
        print(f"Faces: {len(base.Faces())}, Edges: {len(base.Edges())}, Solids: {len(base.Solids())}")
    except Exception as e:
        print(f"Basic shape stats failed: {e}")

    chamfer_size = 0.2

    # Conservative "hole-mouth" proxy: full-circle edges.
    # (These typically correspond to hole openings; arcs/fillets are excluded.)
    candidates = []
    for e in base.Edges():
        try:
            gt = str(getattr(e, "geomType", lambda: "")()).upper()
            if gt != "CIRCLE":
                continue
            r = float(e.radius())
            if r <= 1e-9:
                continue
            L = float(e.Length())
            if abs(L - 2.0 * math.pi * r) > 0.05:  # mm tolerance
                continue
            candidates.append(e)
        except Exception:
            continue

    print(f"Full-circle edge candidates: {len(candidates)}")
    if not candidates:
        print("No hole edges found to chamfer; returning original model.")
        return cq.Workplane(obj=base)

    # Try one-pass chamfer (preferred). If it fails, fall back to sequential chamfers.
    try:
        res = cq.Workplane(obj=base).newObject(candidates).chamfer(chamfer_size)
        print(f"Applied {chamfer_size} mm chamfer to {len(candidates)} edges (one pass).")
        return res
    except Exception as e:
        print(f"One-pass chamfer failed: {e}")

    current = base
    success = 0
    for ed in candidates:
        try:
            current = cq.Workplane(obj=current).newObject([ed]).chamfer(chamfer_size).val()
            success += 1
        except Exception:
            continue

    print(f"Sequential chamfer successes: {success} / {len(candidates)}")
    return cq.Workplane(obj=current)
