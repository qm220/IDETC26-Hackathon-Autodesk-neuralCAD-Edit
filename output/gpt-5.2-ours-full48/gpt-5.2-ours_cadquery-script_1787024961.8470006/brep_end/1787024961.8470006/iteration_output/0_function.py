def my_cad_function(args):
    import cadquery as cq
    import os
    
    # ---- Load input STEP ----
    if "input_file" not in args:
        raise ValueError("args['input_file'] is required for this edit task")
    input_path = os.path.expanduser(args["input_file"])
    shape = cq.importers.importStep(input_path)
    wp = cq.Workplane(obj=shape)

    # ---- Basic model interrogation (units heuristic) ----
    bb = wp.val().BoundingBox()
    dx, dy, dz = (bb.xlen, bb.ylen, bb.zlen)
    max_dim = max(dx, dy, dz)
    print(f"[DBG] BBox lens: dx={dx:.4f}, dy={dy:.4f}, dz={dz:.4f}, max={max_dim:.4f}")

    # Heuristic: if part max dimension is small (<~50), likely inches; otherwise mm.
    # The planning data has radii ~0.4,0.75,0.8,1.4 which strongly suggests inches.
    units = "inch" if max_dim < 50 else "mm"
    print(f"[DBG] Units heuristic: {units}")

    chamfer_mm = 0.2
    chamfer_size = chamfer_mm / 25.4 if units == "inch" else chamfer_mm
    print(f"[DBG] Chamfer size in model units: {chamfer_size:.6f}")

    # ---- Select through-hole end edges (both sides) by circular edge radius ----
    # Expected hole radii from planning stage:
    #  - mounting through-holes: r=0.4
    #  - clevis pin bores: r=0.75
    # These values are assumed to be in model units.
    hole_radii = [0.4, 0.75]
    tol = 0.02 if units == "inch" else 0.5  # loose enough to survive import tolerances

    circ_edges = wp.edges(cq.selectors.TypeSelector("CIRCLE")).vals()
    print(f"[DBG] Total circular edges found: {len(circ_edges)}")

    sel_edges = []
    for e in circ_edges:
        try:
            r = e.radius()
        except Exception:
            continue
        if any(abs(r - hr) <= tol for hr in hole_radii):
            sel_edges.append(e)

    # De-dup by hashCode (OCC) if available
    unique = []
    seen = set()
    for e in sel_edges:
        try:
            key = e.hashCode(2147483647)
        except Exception:
            key = id(e)
        if key not in seen:
            seen.add(key)
            unique.append(e)

    print(f"[DBG] Candidate hole-end circular edges selected: {len(unique)}")
    if len(unique) == 0:
        print("[WARN] No hole edges matched expected radii; no chamfer applied.")
        return wp

    # ---- Apply 0.2 mm equal-distance chamfer (45 deg) ----
    result = wp.newObject(unique).chamfer(chamfer_size)

    return result
