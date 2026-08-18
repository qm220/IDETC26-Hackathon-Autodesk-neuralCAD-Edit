def my_cad_function(args):
    import cadquery as cq
    import os
    from collections import defaultdict

    input_file = os.path.expanduser(args.get("input_file", ""))
    if not input_file or not os.path.exists(input_file):
        raise ValueError(f"Missing or invalid args['input_file']: {input_file}")

    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported

    # pick biggest solid
    solids = list(cq.Workplane(obj=root).solids().vals()) if not hasattr(root, "Solids") else list(root.Solids())
    if not solids:
        raise ValueError("No solids found in imported STEP")
    main = max(solids, key=lambda s: float(s.Volume()))

    bb = main.BoundingBox()
    xmin, xmax = bb.xmin, bb.xmax
    ymin, ymax = bb.ymin, bb.ymax
    zmin, zmax = bb.zmin, bb.zmax
    xlen, ylen, zlen = bb.xlen, bb.ylen, bb.zlen

    print(f"MAIN BBOX: x[{xmin:.3f},{xmax:.3f}] y[{ymin:.3f},{ymax:.3f}] z[{zmin:.3f},{zmax:.3f}]")

    # --- OCC helpers for adjacency and surface typing ---
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape
    from OCP.TopExp import TopExp
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
    from OCP.TopTools import TopTools_ListIteratorOfListOfShape
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane, GeomAbs_Cylinder
    from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet

    # head region on x-min side; keep away from pocket (starts ~x=125) and shoulder (~x=100)
    head_x_limit = xmin + min(102.0, 0.38 * xlen)

    tol = max(0.15, 0.003 * max(xlen, ylen, zlen))
    tolY = max(0.40, 0.01 * ylen)

    def is_line_edge(e: cq.Edge):
        try:
            return e.geomType() == "LINE"
        except Exception:
            return False

    def edge_center(e: cq.Edge):
        try:
            return e.Center()
        except Exception:
            return e.centerOfMass()

    def in_head_region(e: cq.Edge):
        c = edge_center(e)
        return c.x <= head_x_limit + tol

    def near(va, vb, t):
        return abs(va - vb) <= t

    def touches_outer_extents(e: cq.Edge):
        eb = e.BoundingBox()
        return (
            near(eb.xmin, xmin, tol) or near(eb.xmax, xmax, tol) or
            near(eb.ymin, ymin, tol) or near(eb.ymax, ymax, tol) or
            near(eb.zmin, zmin, tol) or near(eb.zmax, zmax, tol)
        )

    def near_y_side(e: cq.Edge, yside: float):
        eb = e.BoundingBox()
        return near(eb.ymin, yside, tolY) or near(eb.ymax, yside, tolY)

    # Build edge->faces adjacency map
    anc = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors(main.wrapped, TopAbs_EDGE, TopAbs_FACE, anc)

    def edge_adjacent_face_types(e: cq.Edge):
        """Return list of OCC surface type enums for faces adjacent to this edge."""
        types = []
        if not anc.Contains(e.wrapped):
            return types
        lst = anc.FindFromKey(e.wrapped)
        it = TopTools_ListIteratorOfListOfShape(lst)
        while it.More():
            f = it.Value()  # TopoDS_Face as shape
            try:
                ad = BRepAdaptor_Surface(f)
                types.append(ad.GetType())
            except Exception:
                pass
            it.Next()
        return types

    def is_plane_plane_sharp(e: cq.Edge):
        if not is_line_edge(e):
            return False
        ftypes = edge_adjacent_face_types(e)
        if len(ftypes) < 2:
            return False
        # consider only the first two; typical manifold edge has 2 adjacent faces
        return (ftypes[0] == GeomAbs_Plane) and (ftypes[1] == GeomAbs_Plane)

    # Determine which Y side is missing radii by counting plane-plane sharp outer edges in head region
    def sharp_count_on_y(yside: float):
        cnt = 0
        for e in main.Edges():
            if not in_head_region(e):
                continue
            if not near_y_side(e, yside):
                continue
            if not touches_outer_extents(e):
                continue
            if is_plane_plane_sharp(e):
                cnt += 1
        return cnt

    cnt_ymin = sharp_count_on_y(ymin)
    cnt_ymax = sharp_count_on_y(ymax)
    bad_side = ymax if cnt_ymax > cnt_ymin else ymin
    good_side = ymin if bad_side == ymax else ymax

    print(f"Plane-plane sharp edge count near y={ymin:.3f}: {cnt_ymin}")
    print(f"Plane-plane sharp edge count near y={ymax:.3f}: {cnt_ymax}")
    print(f"Assuming missing-radii side is y={bad_side:.3f} (good side y={good_side:.3f})")

    # Detect reference radius from existing cylindrical faces near the good side in the head region
    r_ref = 30.0
    radii_bins = defaultdict(float)  # radius_bin -> total area

    for f in main.Faces():
        try:
            fc = f.Center()
            if fc.x > head_x_limit + 2 * tol:
                continue
            fb = f.BoundingBox()
            if not (near(fb.ymin, good_side, tolY) or near(fb.ymax, good_side, tolY)):
                continue
            ad = BRepAdaptor_Surface(f.wrapped)
            if ad.GetType() != GeomAbs_Cylinder:
                continue
            r = float(ad.Cylinder().Radius())
            if r < 8.0 or r > 80.0:
                continue
            a = float(f.Area())
            b = round(r * 2.0) / 2.0  # 0.5mm bin
            radii_bins[b] += a
        except Exception:
            continue

    if radii_bins:
        # Prefer larger head radii
        candidates = [(b, a) for b, a in radii_bins.items() if b >= 10.0]
        if candidates:
            candidates.sort(key=lambda t: t[1], reverse=True)
            r_ref = float(candidates[0][0])

    print(f"Using reference fillet radius r_ref={r_ref:.3f}")

    # Collect edges to fillet: sharp (plane-plane) external edges on the bad side within head region,
    # and close to the left head (avoid shoulder by keeping x well below ~100).
    edges_to_fillet = []
    for e in main.Edges():
        if not in_head_region(e):
            continue
        if not near_y_side(e, bad_side):
            continue
        if not touches_outer_extents(e):
            continue
        c = edge_center(e)
        if c.x > xmin + 92.0 + tol:
            continue
        if not is_plane_plane_sharp(e):
            continue
        edges_to_fillet.append(e)

    print(f"Selected sharp edges to fillet on bad side: {len(edges_to_fillet)}")

    # Apply fillet using OCC. Try all-at-once; if it fails, fall back to one-by-one.
    result_shape = main.wrapped

    def try_fillet(shape_wrapped, edge_list):
        mk = BRepFilletAPI_MakeFillet(shape_wrapped)
        for ee in edge_list:
            mk.Add(r_ref, ee.wrapped)
        mk.Build()
        if not mk.IsDone():
            return None
        return mk.Shape()

    if edges_to_fillet:
        out = try_fillet(result_shape, edges_to_fillet)
        if out is None:
            print("Bulk fillet failed; trying per-edge fillets...")
            # per-edge fallback
            applied = 0
            kept = 0
            for ee in edges_to_fillet:
                kept += 1
                mk = BRepFilletAPI_MakeFillet(result_shape)
                mk.Add(r_ref, ee.wrapped)
                mk.Build()
                if mk.IsDone():
                    result_shape = mk.Shape()
                    applied += 1
                else:
                    # skip edge if it cannot be filleted at this radius
                    pass
            print(f"Per-edge fillet applied on {applied}/{kept} edges.")
        else:
            result_shape = out
            print("Bulk fillet applied successfully.")

    result = cq.Shape.cast(result_shape)
    bb2 = result.BoundingBox()
    print(f"FINAL BBOX: x[{bb2.xmin:.3f},{bb2.xmax:.3f}] y[{bb2.ymin:.3f},{bb2.ymax:.3f}] z[{bb2.zmin:.3f},{bb2.zmax:.3f}]")

    return cq.Workplane(obj=result)
