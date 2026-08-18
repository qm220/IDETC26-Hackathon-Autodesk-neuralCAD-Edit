def my_cad_function(args):
    import cadquery as cq
    import os, math
    from collections import defaultdict

    input_file = os.path.expanduser(args.get("input_file", ""))
    if not input_file or not os.path.exists(input_file):
        raise ValueError(f"Missing or invalid args['input_file']: {input_file}")

    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported

    wp_root = cq.Workplane(obj=root)
    solids = list(wp_root.solids().vals())
    if not solids:
        raise ValueError("No solids found in imported STEP")

    main = max(solids, key=lambda s: float(s.Volume()))
    others = [s for s in solids if s is not main]

    bb = main.BoundingBox()
    xmin, xmax = bb.xmin, bb.xmax
    ymin, ymax = bb.ymin, bb.ymax
    zmin, zmax = bb.zmin, bb.zmax
    xlen, ylen, zlen = bb.xlen, bb.ylen, bb.zlen

    print(f"MAIN BBOX: x[{xmin:.3f},{xmax:.3f}] y[{ymin:.3f},{ymax:.3f}] z[{zmin:.3f},{zmax:.3f}]")

    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GeomAbs import GeomAbs_Circle
    from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet

    # region assumptions
    head_x_limit = xmin + min(115.0, 0.40 * xlen)  # big left mass region

    # tolerances
    tol = max(0.25, 0.004 * max(xlen, ylen, zlen))
    tolY = max(0.75, 0.015 * ylen)

    def near(a, b, t):
        return abs(a - b) <= t

    def edge_center(e: cq.Edge):
        try:
            return e.Center()
        except Exception:
            return e.centerOfMass()

    def in_head_region(e: cq.Edge):
        return edge_center(e).x <= head_x_limit + tol

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

    def is_circle_edge(e: cq.Edge):
        try:
            ad = BRepAdaptor_Curve(e.wrapped)
            return ad.GetType() == GeomAbs_Circle
        except Exception:
            return False

    def circle_radius(e: cq.Edge):
        ad = BRepAdaptor_Curve(e.wrapped)
        return float(ad.Circle().Radius())

    def is_line_edge(e: cq.Edge):
        try:
            return e.geomType() == "LINE"
        except Exception:
            return False

    # --- Decide which Y side is "good" by how much circular-edge length exists in head region ---
    def circular_length_on_side(yside: float):
        total = 0.0
        for e in main.Edges():
            if not in_head_region(e):
                continue
            if not near_y_side(e, yside):
                continue
            if not touches_outer_extents(e):
                continue
            if not is_circle_edge(e):
                continue
            try:
                r = circle_radius(e)
                if 5.0 <= r <= 120.0:
                    total += float(e.Length())
            except Exception:
                continue
        return total

    circ_ymin = circular_length_on_side(ymin)
    circ_ymax = circular_length_on_side(ymax)

    # assume missing-radii side has LESS circular content
    bad_side = ymin if circ_ymin < circ_ymax else ymax
    good_side = ymax if bad_side == ymin else ymin

    print(f"Circular edge length near y={ymin:.3f}: {circ_ymin:.3f}")
    print(f"Circular edge length near y={ymax:.3f}: {circ_ymax:.3f}")
    print(f"Assuming missing-radii side is y={bad_side:.3f} (reference/good side y={good_side:.3f})")

    # --- Reference radius from good side (dominant circular radius) ---
    r_ref = 30.0
    bins = defaultdict(float)  # radius_bin -> accumulated length

    for e in main.Edges():
        if not in_head_region(e):
            continue
        if not near_y_side(e, good_side):
            continue
        if not touches_outer_extents(e):
            continue
        if not is_circle_edge(e):
            continue
        try:
            r = circle_radius(e)
            if r < 8.0 or r > 120.0:
                continue
            L = float(e.Length())
            b = round(r * 2.0) / 2.0  # 0.5mm bins
            bins[b] += L
        except Exception:
            continue

    if bins:
        # favor larger head radii, but take dominant-by-length among r>=10
        candidates = [(rb, w) for rb, w in bins.items() if rb >= 10.0]
        if candidates:
            candidates.sort(key=lambda t: t[1], reverse=True)
            r_ref = float(candidates[0][0])

    print(f"Using reference fillet radius r_ref={r_ref:.3f}")

    # --- Build candidate target points on the bad side: sharp line edges in head region on outer boundary ---
    candidate_pts = []
    for e in main.Edges():
        if not in_head_region(e):
            continue
        if not near_y_side(e, bad_side):
            continue
        if not touches_outer_extents(e):
            continue
        if not is_line_edge(e):
            continue
        try:
            if float(e.Length()) < 2.0:
                continue
        except Exception:
            continue
        c = edge_center(e)
        candidate_pts.append((c.x, c.y, c.z))

    # Also include any sharp line edges on the left big mass perimeter regardless of y,
    # but keep it constrained to head region so we don't affect the arm/pocket.
    for e in main.Edges():
        if not in_head_region(e):
            continue
        if not touches_outer_extents(e):
            continue
        if not is_line_edge(e):
            continue
        c = edge_center(e)
        # emphasize leftmost region (helps if "left side" meant x-min end)
        if c.x <= xmin + 60.0 + tol:
            candidate_pts.append((c.x, c.y, c.z))

    # de-duplicate points roughly
    uniq = []
    for p in candidate_pts:
        if all((p[0]-q[0])**2 + (p[1]-q[1])**2 + (p[2]-q[2])**2 > (1.0**2) for q in uniq):
            uniq.append(p)
    candidate_pts = uniq

    print(f"Candidate sharp-edge sample points: {len(candidate_pts)}")

    # --- Sequential fillet with spatial edge re-find each step; never throw ---
    current_wrapped = main.wrapped
    applied = 0

    def find_nearest_edge(shape: cq.Shape, pt, require_near_bad_side=True):
        px, py, pz = pt
        best = None
        best_d2 = 1e99
        for e in shape.Edges():
            if not in_head_region(e):
                continue
            if require_near_bad_side and not near_y_side(e, bad_side):
                continue
            if not touches_outer_extents(e):
                continue
            if not is_line_edge(e):
                continue
            c = edge_center(e)
            d2 = (c.x - px) ** 2 + (c.y - py) ** 2 + (c.z - pz) ** 2
            if d2 < best_d2:
                best_d2 = d2
                best = e
        return best, best_d2

    # First pass: try to fillet edges specifically on the detected bad Y side
    for pt in candidate_pts:
        try:
            shape_cq = cq.Shape.cast(current_wrapped)
            e, d2 = find_nearest_edge(shape_cq, pt, require_near_bad_side=True)
            if e is None:
                continue
            if d2 > (3.0 ** 2):
                continue

            mk = BRepFilletAPI_MakeFillet(current_wrapped)
            try:
                mk.Add(r_ref, e.wrapped)
            except Exception:
                continue
            try:
                mk.Build()
            except Exception:
                continue
            if not mk.IsDone():
                continue
            current_wrapped = mk.Shape()
            applied += 1
        except Exception:
            continue

    # Second pass: if nothing applied, try a broader head-region fillet on left big mass edges
    if applied == 0:
        print("No fillets applied on bad-side pass; trying broader left-head pass...")
        # collect representative points again (left region)
        broad_pts = []
        shape_cq = cq.Shape.cast(current_wrapped)
        for e in shape_cq.Edges():
            if not in_head_region(e):
                continue
            if not touches_outer_extents(e):
                continue
            if not is_line_edge(e):
                continue
            c = edge_center(e)
            if c.x <= xmin + 75.0 + tol:
                broad_pts.append((c.x, c.y, c.z))

        # de-dup
        uniq2 = []
        for p in broad_pts:
            if all((p[0]-q[0])**2 + (p[1]-q[1])**2 + (p[2]-q[2])**2 > (1.0**2) for q in uniq2):
                uniq2.append(p)
        broad_pts = uniq2
        print(f"Broad left-head candidate points: {len(broad_pts)}")

        for pt in broad_pts:
            try:
                shape_cq = cq.Shape.cast(current_wrapped)
                e, d2 = find_nearest_edge(shape_cq, pt, require_near_bad_side=False)
                if e is None:
                    continue
                if d2 > (3.0 ** 2):
                    continue

                mk = BRepFilletAPI_MakeFillet(current_wrapped)
                try:
                    mk.Add(r_ref, e.wrapped)
                except Exception:
                    continue
                try:
                    mk.Build()
                except Exception:
                    continue
                if not mk.IsDone():
                    continue
                current_wrapped = mk.Shape()
                applied += 1
            except Exception:
                continue

    print(f"Fillet applications succeeded: {applied}")

    result_main = cq.Shape.cast(current_wrapped)

    # Recombine with other solids if present
    if others:
        comp = cq.Compound.makeCompound([result_main] + others)
        result = cq.Workplane(obj=comp)
    else:
        result = cq.Workplane(obj=result_main)

    bb2 = result.val().BoundingBox() if hasattr(result, "val") else result_main.BoundingBox()
    print(f"FINAL BBOX: x[{bb2.xmin:.3f},{bb2.xmax:.3f}] y[{bb2.ymin:.3f},{bb2.ymax:.3f}] z[{bb2.zmin:.3f},{bb2.zmax:.3f}]")

    return result
