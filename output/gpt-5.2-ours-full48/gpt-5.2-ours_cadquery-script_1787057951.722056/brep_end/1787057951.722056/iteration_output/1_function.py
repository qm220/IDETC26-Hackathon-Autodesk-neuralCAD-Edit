def my_cad_function(args):
    import cadquery as cq
    import os, math

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

    thk = float(bbox.ylen)
    if thk <= 0:
        raise ValueError("Invalid thickness (bbox.ylen <= 0)")

    # -----------------------------
    # Find the ring through-hole circle edge (r ~ 10) on the bottom face
    # -----------------------------
    bottom_faces = model.faces("<Y").vals()
    print(f"Bottom faces (<Y) count: {len(bottom_faces)}")
    if not bottom_faces:
        raise ValueError("No bottom faces found with selector <Y")

    bottom_face = max(bottom_faces, key=lambda f: f.Area())

    circ_edges = []
    try:
        circ_edges = cq.Workplane(obj=bottom_face).edges("%Circle").vals()
    except Exception:
        # fallback: scan bottom face edges and keep circle-like edges
        circ_edges = bottom_face.Edges()

    print(f"Bottom face circle-typed edges found (pre-filter): {len(circ_edges)}")

    hole_edge = None
    best_score = 1e9

    for e in circ_edges:
        # radius
        try:
            r = float(e.radius())
        except Exception:
            continue

        # Filter around expected ~10mm radius (from planning data)
        if not (7.0 <= r <= 13.0):
            continue

        # Prefer (near) full circles over arcs
        try:
            L = float(e.Length())
        except Exception:
            L = None

        full_circle_ratio = 0.0
        if L is not None and r > 1e-9:
            full_circle_ratio = L / (2.0 * math.pi * r)

        # center
        c = None
        for meth in ("Center", "center"):
            try:
                c = getattr(e, meth)()
                break
            except Exception:
                pass
        if c is None:
            continue

        # Score: closeness to r=10 plus penalty if not close to a full circle
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
                r = float(e.radius())
            except Exception:
                continue
            if not (7.0 <= r <= 13.0):
                continue
            try:
                L = float(e.Length())
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
    c = None
    for meth in ("Center", "center"):
        try:
            c = getattr(hole_edge, meth)()
            break
        except Exception:
            pass
    if c is None:
        raise ValueError("Failed to obtain center of selected hole circular edge")

    cx, cy, cz = float(c.x), float(c.y), float(c.z)
    print(f"Chosen hole reference: r={hole_r:.6f}, center=({cx:.6f}, {cy:.6f}, {cz:.6f}), score={best_score:.6f}")

    # -----------------------------
    # 1) Fill existing cylindrical through-hole (so we truly replace it)
    # Use a tiny oversize and extra length to avoid coincident faces.
    # -----------------------------
    plug_r = hole_r + 0.02
    plug_extra = 0.5
    plug = (
        cq.Workplane("XZ")
        .workplane(offset=bbox.ymin - plug_extra / 2.0)
        .center(cx, cz)
        .circle(plug_r)
        .extrude(thk + plug_extra)
    )

    filled = model.union(plug)

    # -----------------------------
    # 2) Cut an inscribed hex THROUGH ALL (vertices on the original circle)
    # Orientation: one flat/edge parallel to handle direction (global Z).
    # In XZ sketch plane, making one edge parallel to +Z occurs with ang0 = -30 deg.
    # -----------------------------
    ang0 = math.radians(-30.0)
    pts = []
    for i in range(6):
        a = ang0 + i * (math.pi / 3.0)
        pts.append((hole_r * math.cos(a), hole_r * math.sin(a)))

    cut_extra = 2.0
    hex_prism = (
        cq.Workplane("XZ")
        .workplane(offset=bbox.ymin - cut_extra / 2.0)
        .center(cx, cz)
        .polyline(pts)
        .close()
        .extrude(thk + cut_extra)
    )

    result = filled.cut(hex_prism)

    out = result.val() if hasattr(result, "val") else result
    print(f"Result valid: {out.isValid()}")
    print(f"Result faces: {len(out.Faces())}")

    return result
