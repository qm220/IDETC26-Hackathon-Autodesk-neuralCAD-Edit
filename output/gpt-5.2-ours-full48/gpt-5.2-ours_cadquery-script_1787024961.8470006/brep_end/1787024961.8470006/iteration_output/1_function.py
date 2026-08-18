def my_cad_function(args):
    import cadquery as cq
    import os

    if "input_file" not in args:
        raise ValueError("args['input_file'] is required for this edit task")

    input_path = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_path)

    # --- Normalize imported object to a single Shape for robust processing ---
    root_shape = None
    if isinstance(imported, cq.Workplane):
        root_shape = imported.val()
    elif hasattr(cq, "Assembly") and isinstance(imported, cq.Assembly):
        root_shape = imported.toCompound()
    else:
        root_shape = imported

    # --- Units heuristic (safe) ---
    units = "inch"  # default assumption for this dataset
    try:
        bb = root_shape.BoundingBox()
        dx, dy, dz = (bb.xlen, bb.ylen, bb.zlen)
        max_dim = max(dx, dy, dz)
        print(f"[DBG] BBox lens: dx={dx:.4f}, dy={dy:.4f}, dz={dz:.4f}, max={max_dim:.4f}")
        # If dimensions are large, likely mm; if small, likely inches.
        units = "inch" if max_dim < 50 else "mm"
    except Exception as e:
        print(f"[WARN] Could not compute BoundingBox for units heuristic: {e}")

    chamfer_mm = 0.2
    chamfer_size = chamfer_mm / 25.4 if units == "inch" else chamfer_mm
    print(f"[DBG] Units heuristic: {units}")
    print(f"[DBG] Chamfer size in model units: {chamfer_size:.6f}")

    # Expected hole radii from planning stage are likely in inches.
    # Convert to model units depending on detected units.
    hole_r_in = [0.4, 0.75]  # mounting holes, clevis pin bores
    hole_r = [r if units == "inch" else r * 25.4 for r in hole_r_in]

    # Tolerances (imported STEP may have slight numeric noise)
    tol_r = 0.02 if units == "inch" else 0.5

    wp = cq.Workplane(obj=root_shape)

    cyl_faces = wp.faces(cq.selectors.TypeSelector("CYLINDER")).vals()
    print(f"[DBG] Total cylindrical faces found: {len(cyl_faces)}")

    # Collect only cylindrical faces that match the hole radii (exclude bosses, rounds, etc.)
    hole_cyl_faces = []
    for f in cyl_faces:
        r = None
        try:
            r = f.radius()
        except Exception:
            r = None
        if r is None:
            continue
        if any(abs(r - hr) <= tol_r for hr in hole_r):
            hole_cyl_faces.append(f)

    print(f"[DBG] Candidate hole cylindrical faces (by radius): {len(hole_cyl_faces)}")

    # From each hole-cylinder face, pick its circular boundary edges (these are the end edges)
    cand_edges = []
    for f in hole_cyl_faces:
        for e in f.Edges():
            try:
                if e.geomType() != "CIRCLE":
                    continue
                er = e.radius()
                if any(abs(er - hr) <= tol_r for hr in hole_r):
                    cand_edges.append(e)
            except Exception:
                continue

    # De-dup edges
    unique_edges = []
    seen = set()
    for e in cand_edges:
        try:
            key = e.hashCode(2147483647)
        except Exception:
            key = id(e)
        if key not in seen:
            seen.add(key)
            unique_edges.append(e)

    print(f"[DBG] Hole end circular edges selected for chamfer: {len(unique_edges)}")

    if len(unique_edges) == 0:
        print("[WARN] No hole end edges found; chamfer not applied.")
        return wp

    # Apply equal-distance (45deg) chamfer
    result = wp.newObject(unique_edges).chamfer(chamfer_size)
    return result
