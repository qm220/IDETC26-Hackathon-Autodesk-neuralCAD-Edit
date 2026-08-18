def my_cad_function(args):
    """Edit STEP model: add retaining cylindrical heads (collars) to both ends of the 4 long corner pins."""
    import os
    import math

    if "input_file" not in args:
        raise ValueError("args['input_file'] is required for edit tasks")

    input_file = os.path.expanduser(args["input_file"])
    wp = cq.importers.importStep(input_file)

    # Underlying OCC shape
    base_shape = wp.val() if hasattr(wp, "val") else wp

    solids = list(base_shape.Solids())
    print(f"Loaded STEP: {input_file}")
    print(f"Total solids found: {len(solids)}")

    # Heuristic: corner pivot pins are the only long, near-cylindrical solids aligned in Z
    pin_candidates = []
    for i, s in enumerate(solids):
        bb = s.BoundingBox()
        xlen, ylen, zlen = bb.xlen, bb.ylen, bb.zlen
        max_xy = max(xlen, ylen)
        min_xy = min(xlen, ylen)
        aspect = (zlen / max_xy) if max_xy > 1e-9 else 0

        # Keep thresholds tolerant; pins are long in Z, small in X/Y.
        if zlen > 20 and max_xy < 15 and aspect > 2.5:
            cx, cy, cz = bb.center.x, bb.center.y, bb.center.z
            pin_candidates.append((i, s, bb, cx, cy, cz, xlen, ylen, zlen, aspect))

    print(f"Pin candidates (heuristic) found: {len(pin_candidates)}")
    for (i, _s, bb, cx, cy, cz, xlen, ylen, zlen, aspect) in pin_candidates:
        print(
            f"  cand solid[{i}]: center=({cx:.3f},{cy:.3f},{cz:.3f})  lens=({xlen:.3f},{ylen:.3f},{zlen:.3f})  aspect={aspect:.2f}  z=({bb.zmin:.3f},{bb.zmax:.3f})"
        )

    # If heuristic finds more than 4, keep the 4 longest (should be corner pins)
    pin_candidates.sort(key=lambda t: t[8], reverse=True)  # by zlen
    pins = pin_candidates[:4]
    print(f"Pins selected for head addition: {len(pins)}")

    # Build collar heads (two per pin) and union them to the model
    head_solids = []
    for (_idx, _s, bb, cx, cy, cz, xlen, ylen, zlen, aspect) in pins:
        # Estimate pin radius from XY envelope; use smaller of x/y (more robust if minor blends exist)
        r_est = 0.25 * (xlen + ylen)
        # Retaining head parameters (chosen conservatively)
        head_thk = 2.0  # mm
        head_r = max(r_est * 1.8, r_est + 1.5)  # ensure noticeably larger than shank

        zmin = bb.zmin
        zmax = bb.zmax

        # Negative-Z end head: from (zmin - head_thk) to zmin
        head_neg = cq.Solid.makeCylinder(
            head_r,
            head_thk,
            pnt=cq.Vector(cx, cy, zmin - head_thk),
            dir=cq.Vector(0, 0, 1),
        )
        # Positive-Z end head: from zmax to (zmax + head_thk)
        head_pos = cq.Solid.makeCylinder(
            head_r,
            head_thk,
            pnt=cq.Vector(cx, cy, zmax),
            dir=cq.Vector(0, 0, 1),
        )

        head_solids.extend([head_neg, head_pos])
        print(
            f"  Added heads at pin center ({cx:.3f},{cy:.3f}); r_est={r_est:.3f}, head_r={head_r:.3f}, head_thk={head_thk:.3f}, zmin={zmin:.3f}, zmax={zmax:.3f}"
        )

    if not head_solids:
        print("WARNING: No heads created (no pins detected). Returning original model.")
        return wp

    heads_comp = cq.Compound.makeCompound(head_solids)
    result = wp.union(cq.Workplane("XY").newObject([heads_comp]))

    return result
