def my_cad_function(args):
    import cadquery as cq
    import os, math

    # --- Load model ---
    if "input_file" not in args:
        raise ValueError("args['input_file'] is required for edit tasks")
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)

    shp = model.val() if hasattr(model, "val") else model
    bbox = shp.BoundingBox()
    print(f"Loaded STEP: {input_file}")
    print(f"IsValid: {shp.isValid()}")
    print(
        "BBox: "
        f"xmin={bbox.xmin:.4f}, xmax={bbox.xmax:.4f}, "
        f"ymin={bbox.ymin:.4f}, ymax={bbox.ymax:.4f}, "
        f"zmin={bbox.zmin:.4f}, zmax={bbox.zmax:.4f}"
    )

    thk = bbox.ylen
    if thk <= 0:
        raise ValueError("Invalid thickness (bbox.ylen <= 0)")

    # --- Find the existing ring through-hole from the bottom face circular edge ---
    bottom_face_sel = model.faces("<Y").sortByArea().first()
    circ_edges = bottom_face_sel.edges("%Circle").vals()
    print(f"Bottom face circle-typed edges found: {len(circ_edges)}")

    hole_edge = None
    best_score = 1e9

    for e in circ_edges:
        # radius
        try:
            r = e.radius()
        except Exception:
            continue

        # Filter around expected ~10mm radius (from planning data)
        if not (7.0 <= r <= 13.0):
            continue

        # Prefer (near) full circles over arcs
        try:
            L = e.Length()
        except Exception:
            L = None

        full_circle_ratio = None
        if L is not None and r > 1e-9:
            full_circle_ratio = L / (2.0 * math.pi * r)
        else:
            full_circle_ratio = 0.0

        # center estimate
        try:
            c = e.Center()
        except Exception:
            try:
                c = e.center()
            except Exception:
                c = None

        if c is None:
            continue

        # Score: closeness to r=10 plus preference for full-circle
        score = abs(r - 10.0) + (0.0 if full_circle_ratio > 0.80 else 5.0)

        if score < best_score:
            best_score = score
            hole_edge = e

    if hole_edge is None:
        # Fallback: search all circular edges in model
        print("WARNING: Could not identify hole edge on bottom face; falling back to global circle edges.")
        all_circ = model.edges("%Circle").vals()
        print(f"Global circle-typed edges found: {len(all_circ)}")
        for e in all_circ:
            try:
                r = e.radius()
            except Exception:
                continue
            if not (7.0 <= r <= 13.0):
                continue
            try:
                L = e.Length()
            except Exception:
                L = None
            full_circle_ratio = (L / (2.0 * math.pi * r)) if (L is not None and r > 1e-9) else 0.0
            score = abs(r - 10.0) + (0.0 if full_circle_ratio > 0.80 else 5.0)
            if score < best_score:
                best_score = score
                hole_edge = e

    if hole_edge is None:
        raise ValueError("Failed to locate the ring through-hole circular edge to reference the hex.")

    hole_r = float(hole_edge.radius())
    try:
        hole_c = hole_edge.Center()
    except Exception:
        hole_c = hole_edge.center()

    cx, cz = float(hole_c.x), float(hole_c.z)
    print(f"Chosen hole reference: r={hole_r:.6f}, center=({cx:.6f}, {hole_c.y:.6f}, {cz:.6f}), score={best_score:.6f}")

    # --- 1) Fill the existing cylindrical through-hole (so we can truly 'replace' it) ---
    # Create a plug cylinder exactly spanning the part thickness.
    # Axis is along +Y (normal to XZ plane).
    plug = (
        cq.Workplane("XZ")
        .workplane(offset=bbox.ymin)
        .center(cx, cz)
        .circle(hole_r)
        .extrude(thk)
    )

    filled = model.union(plug)

    # --- 2) Cut an inscribed hex through all (vertices on the original hole circle) ---
    # Orientation: make one flat parallel to handle direction (global Z).
    # Using a 30° rotation produces a hex with vertical side flats in the (X,Z) sketch plane.
    ang0 = math.radians(30.0)
    pts = []
    for i in range(6):
        a = ang0 + i * (math.pi / 3.0)
        pts.append((hole_r * math.cos(a), hole_r * math.sin(a)))

    # Extrude a prism that fully spans beyond the thickness, then boolean cut.
    cut_height = thk + 2.0
    hex_prism = (
        cq.Workplane("XZ")
        .workplane(offset=bbox.ymin - 1.0)
        .center(cx, cz)
        .polyline(pts)
        .close()
        .extrude(cut_height)
    )

    result = filled.cut(hex_prism)

    # Debug summary
    out = result.val() if hasattr(result, "val") else result
    print(f"Result valid: {out.isValid()}")
    print(f"Result faces: {len(out.Faces())}")

    return result
