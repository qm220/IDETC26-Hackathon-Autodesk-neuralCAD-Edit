def my_cad_function(args):
    import cadquery as cq
    import os

    input_file = os.path.expanduser(args.get("input_file", ""))
    if not input_file or not os.path.exists(input_file):
        raise ValueError(f"Missing or invalid args['input_file']: {input_file}")

    model = cq.importers.importStep(input_file)
    solid = model.val() if hasattr(model, "val") else model

    if not solid.isValid():
        print("WARNING: imported solid reports isValid() == False")

    bb = solid.BoundingBox()
    xmin, xmax = bb.xmin, bb.xmax
    ymin, ymax = bb.ymin, bb.ymax
    zmin, zmax = bb.zmin, bb.zmax
    xlen, ylen, zlen = bb.xlen, bb.ylen, bb.zlen

    print(f"BBOX: x[{xmin:.3f},{xmax:.3f}] (len {xlen:.3f})  y[{ymin:.3f},{ymax:.3f}] (len {ylen:.3f})  z[{zmin:.3f},{zmax:.3f}] (len {zlen:.3f})")

    # Heuristic: 'bigger part' == main body excluding the far right 'nose' details.
    x_cut = xmin + 0.90 * xlen

    # Side tolerance for selecting edges that lie on the extreme side face
    tolY = max(0.5, 0.01 * ylen)

    edges = list(solid.Edges())

    def ecenter(e):
        try:
            return e.Center()
        except Exception:
            return e.centerOfMass()

    def is_line(e):
        try:
            return e.geomType() == "LINE"
        except Exception:
            return False

    def is_circle(e):
        try:
            return e.geomType() == "CIRCLE"
        except Exception:
            return False

    # Count sharp (LINE) edges on each side to guess which side is missing fillets
    sharp_minY = []
    sharp_maxY = []
    for e in edges:
        if not is_line(e):
            continue
        c = ecenter(e)
        if c.x > x_cut:
            continue
        if abs(c.y - ymin) <= tolY:
            sharp_minY.append(e)
        if abs(c.y - ymax) <= tolY:
            sharp_maxY.append(e)

    print(f"Sharp LINE edges near ymin side: {len(sharp_minY)}")
    print(f"Sharp LINE edges near ymax side: {len(sharp_maxY)}")

    missing_is_min = len(sharp_minY) >= len(sharp_maxY)
    target_y = ymin if missing_is_min else ymax
    other_y = ymax if missing_is_min else ymin
    side_name = "ymin" if missing_is_min else "ymax"
    print(f"Heuristic chosen missing side: {side_name} (target_y={target_y:.3f})")

    # Try to infer the 'same as the other side' major radius by sampling circular edges near the opposite side.
    inferred_radii = []
    for e in edges:
        if not is_circle(e):
            continue
        c = ecenter(e)
        if c.x > x_cut:
            continue
        if abs(c.y - other_y) <= tolY:
            try:
                r = float(e.radius())
                if 0.5 <= r <= 200:
                    inferred_radii.append(r)
            except Exception:
                pass

    inferred_radii_sorted = sorted(inferred_radii)
    if inferred_radii_sorted:
        # Use the maximum as the 'big' body fillet radius (matches planning-stage R30-class behavior)
        fillet_r = inferred_radii_sorted[-1]
    else:
        fillet_r = 30.0

    # Clamp to a reasonable range; keep as float
    fillet_r = float(max(1.0, min(80.0, fillet_r)))
    print(f"Inferred major fillet radius from opposite side: {fillet_r:.3f} (samples={len(inferred_radii_sorted)})")

    # Build the edge set to fillet: sharp (LINE) edges located on the target side face, excluding far-right nose.
    # Also exclude extremely short edges which often cause fillet failures.
    target_edges = []
    for e in edges:
        if not is_line(e):
            continue
        c = ecenter(e)
        if c.x > x_cut:
            continue
        if abs(c.y - target_y) > tolY:
            continue
        try:
            if e.Length() < max(2.0, 0.25 * fillet_r):
                continue
        except Exception:
            pass
        target_edges.append(e)

    print(f"Candidate target edges to fillet on {side_name}: {len(target_edges)}")

    # Apply fillet. If it fails, fall back to a slightly smaller radius (still trying to match as close as possible).
    wp = cq.Workplane(obj=solid)
    try:
        result = wp.newObject(target_edges).fillet(fillet_r)
        print(f"Applied fillet R={fillet_r:.3f} to {len(target_edges)} edges")
        return result
    except Exception as e:
        print(f"Fillet failed at inferred radius R={fillet_r:.3f}: {e}")
        # Fallback: try a modest reduction to improve robustness (will refine after viewing)
        fallback_r = max(1.0, 0.85 * fillet_r)
        print(f"Trying fallback fillet radius R={fallback_r:.3f}")
        result = wp.newObject(target_edges).fillet(fallback_r)
        return result
