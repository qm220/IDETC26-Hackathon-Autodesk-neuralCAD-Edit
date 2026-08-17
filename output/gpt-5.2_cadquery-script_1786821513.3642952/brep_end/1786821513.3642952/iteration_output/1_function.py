def my_cad_function(args):
    import os
    import math
    import cadquery as cq

    if "input_file" not in args:
        print("No input_file provided")
        return None

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    occ = model.val() if hasattr(model, "val") else model

    print(f"Loaded STEP: {input_file}")
    print(f"Valid: {occ.isValid()}")
    print(f"Solids: {len(occ.Solids())}, Faces: {len(occ.Faces())}, Edges: {len(occ.Edges())}")

    bbox = occ.BoundingBox()
    xmid = 0.5 * (bbox.xmin + bbox.xmax)
    y_front = bbox.ymax
    zmid = 0.5 * (bbox.zmin + bbox.zmax)
    print(
        f"Overall BBox: xmin={bbox.xmin:.3f} xmax={bbox.xmax:.3f} "
        f"ymin={bbox.ymin:.3f} ymax={bbox.ymax:.3f} "
        f"zmin={bbox.zmin:.3f} zmax={bbox.zmax:.3f}"
    )

    # --- Find a TORUS face near the front and near the center ---
    torus_cands = []
    faces = occ.Faces()
    for i, f in enumerate(faces):
        try:
            gt = str(f.geomType()).upper()
        except Exception:
            continue
        if gt != "TORUS":
            continue
        fb = f.BoundingBox()
        fc = fb.center
        radial = math.hypot(fc.x - xmid, fc.z - zmid)
        # prefer faces that actually reach the front (large y) and are near center
        score = abs(y_front - fb.ymax) + 0.15 * radial
        torus_cands.append((score, i, f, fb, fc, radial))

    torus_cands.sort(key=lambda t: t[0])
    print(f"Torus faces found: {len(torus_cands)}")
    for k, (score, i, _f, fb, fc, radial) in enumerate(torus_cands[:8]):
        print(
            f"  torus[{k}] faceIndex={i} score={score:.4f} "
            f"center=({fc.x:.3f},{fc.y:.3f},{fc.z:.3f}) radialToMid={radial:.3f} "
            f"ymax={fb.ymax:.3f} ylen={fb.ylen:.3f}"
        )

    if not torus_cands:
        print("No TORUS faces detected; cannot target a fillet reliably. Returning original.")
        return model

    _, face_index, fillet_face, fb, fc, _radial = torus_cands[0]

    # --- On that torus face, find the circular edge closest to the front ---
    circ_edges = []
    for e in fillet_face.Edges():
        try:
            egt = str(e.geomType()).upper()
        except Exception:
            continue
        if egt != "CIRCLE":
            continue
        eb = e.BoundingBox()
        # prefer edge that lies on/near the front
        circ_edges.append((eb.ymax, e, eb))

    circ_edges.sort(key=lambda t: t[0], reverse=True)
    print(f"Circular edges on selected torus face: {len(circ_edges)}")

    if not circ_edges:
        print("Selected torus face had no circular edges; returning original.")
        return model

    y_edge_max, edge, eb = circ_edges[0]

    # Estimate circle center and radius from bounding box (robust for axis-aligned circle)
    cx = eb.center.x
    cz = eb.center.z
    r_est = 0.25 * (eb.xlen + eb.zlen)
    print(
        f"Selected front circular edge: yMax={y_edge_max:.3f} "
        f"centerXZ=({cx:.3f},{cz:.3f}) r~{r_est:.3f} "
        f"edgeBB_ylen={eb.ylen:.6f}"
    )

    # Determine if this is an internal or external edge based on overall radial extent
    corners = [
        (bbox.xmin, bbox.zmin), (bbox.xmin, bbox.zmax),
        (bbox.xmax, bbox.zmin), (bbox.xmax, bbox.zmax),
    ]
    outer_r = max(math.hypot(x - cx, z - cz) for x, z in corners)
    internal_like = r_est < 0.60 * outer_r
    print(f"Outer radial extent about chosen axis: {outer_r:.3f} -> treating edge as {'INTERNAL' if internal_like else 'EXTERNAL'}")

    chamfer = 1.0
    extra = 0.05  # small tolerance to fully remove existing fillet

    # Build a chamfer cutter as an annular/conical frustum near the front face.
    # We'll cut only in a short Y range around the front to avoid affecting the rest.
    y1 = y_front + extra
    y0 = y_front - chamfer - extra
    dy = y1 - y0

    def _wp_xz_at(yval):
        # XZ plane normal is +Y; offset moves along Y
        return cq.Workplane("XZ").workplane(offset=yval).center(cx, cz)

    try:
        if internal_like:
            # Internal chamfer (e.g., at a bore): remove only the ring outside the bore radius.
            r0 = max(0.1, r_est - extra)
            r1 = max(0.1, r_est + chamfer + extra)

            outer = _wp_xz_at(y0).circle(r0).workplane(offset=dy).circle(r1).loft(combine=False)
            inner_r = max(0.05, r_est - 2 * extra)
            inner = _wp_xz_at(y0).circle(inner_r).extrude(dy)
            cutter = outer.cut(inner)
        else:
            # External chamfer: remove only a thin outer ring near the outer boundary.
            r_front = max(0.1, r_est - chamfer)
            r_depth = max(0.1, r_est)
            margin = 2.0

            outer_shell = _wp_xz_at(y0).circle(r_depth + margin).extrude(dy)
            inner_frustum = _wp_xz_at(y0).circle(max(0.1, r_depth - 3 * extra)).workplane(offset=dy).circle(max(0.1, r_front - 3 * extra)).loft(combine=False)
            cutter = outer_shell.cut(inner_frustum)

        result = cq.Workplane(obj=occ).cut(cutter)
        print("Applied revolved frustum cut to replace front-center fillet with ~1mm chamfer.")
        return result

    except Exception as e:
        print(f"Chamfer cutter operation failed: {e}")
        return model
