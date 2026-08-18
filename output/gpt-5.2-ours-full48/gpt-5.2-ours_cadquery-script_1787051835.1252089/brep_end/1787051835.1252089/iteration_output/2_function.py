def my_cad_function(args):
    import cadquery as cq
    import os
    from math import isfinite

    input_file = os.path.expanduser(args.get("input_file", ""))
    if not input_file or not os.path.exists(input_file):
        raise ValueError(f"Missing or invalid args['input_file']: {input_file}")

    wp_in = cq.importers.importStep(input_file)
    root = wp_in.val() if hasattr(wp_in, "val") else wp_in

    def all_solids(shape):
        try:
            return list(shape.Solids())
        except Exception:
            return []

    solids = all_solids(root)
    if not solids:
        try:
            solids = list(wp_in.solids().vals())
        except Exception:
            solids = []
    if not solids:
        raise ValueError("No solids found in imported STEP")

    def vol(s):
        try:
            return float(s.Volume())
        except Exception:
            return 0.0

    main = max(solids, key=vol)

    bb = main.BoundingBox()
    xmin, xmax = bb.xmin, bb.xmax
    ymin, ymax = bb.ymin, bb.ymax
    zmin, zmax = bb.zmin, bb.zmax
    xlen, ylen, zlen = bb.xlen, bb.ylen, bb.zlen

    print(f"MAIN BBOX: x[{xmin:.3f},{xmax:.3f}] y[{ymin:.3f},{ymax:.3f}] z[{zmin:.3f},{zmax:.3f}]")

    # ---- Heuristics ----
    # Head is on x-min side; avoid pocket (starts ~x=125 in metadata) by limiting to ~x<=110
    head_xmax = xmin + min(110.0, 0.38 * xlen)
    shoulder_x = xmin + 100.0  # from planning metadata; keep away from interface

    tolX = max(0.5, 0.015 * xlen)
    tolY = max(0.5, 0.015 * ylen)
    tolZ = max(0.5, 0.015 * zlen)

    def ecenter(e):
        try:
            return e.Center()
        except Exception:
            return e.centerOfMass()

    def fcenter(f):
        try:
            return f.Center()
        except Exception:
            return f.centerOfMass()

    def is_line(e):
        try:
            return e.geomType() == "LINE"
        except Exception:
            return False

    def is_cylinder_face(f):
        try:
            return f.geomType() == "CYLINDER"
        except Exception:
            return False

    def face_radius(f):
        try:
            return float(f.radius())
        except Exception:
            return None

    def touches_plane(val_min, val_max, v, tol):
        return abs(val_min - v) <= tol or abs(val_max - v) <= tol

    edges0 = list(main.Edges())
    faces0 = list(main.Faces())

    # ---- Determine which Y-side is missing radii (compare sharp line edges vs existing cylinders) ----
    def head_line_edges_touching_y(side_y):
        out = []
        for e in edges0:
            if not is_line(e):
                continue
            c = ecenter(e)
            if c.x > head_xmax or c.x > (shoulder_x - 5.0):
                continue
            eb = e.BoundingBox()
            if not touches_plane(eb.ymin, eb.ymax, side_y, tolY):
                continue
            try:
                if e.Length() < 2.0:
                    continue
            except Exception:
                pass
            out.append(e)
        return out

    def head_cyl_faces_touching_y(side_y):
        out = []
        for f in faces0:
            if not is_cylinder_face(f):
                continue
            c = fcenter(f)
            if c.x > head_xmax or c.x > (shoulder_x - 5.0):
                continue
            fb = f.BoundingBox()
            if touches_plane(fb.ymin, fb.ymax, side_y, tolY):
                out.append(f)
        return out

    sharp_ymin = head_line_edges_touching_y(ymin)
    sharp_ymax = head_line_edges_touching_y(ymax)
    cyl_ymin = head_cyl_faces_touching_y(ymin)
    cyl_ymax = head_cyl_faces_touching_y(ymax)

    print(f"Head-region sharp LINE edges touching y-min: {len(sharp_ymin)}")
    print(f"Head-region sharp LINE edges touching y-max: {len(sharp_ymax)}")
    print(f"Head-region CYLINDER faces touching y-min: {len(cyl_ymin)}")
    print(f"Head-region CYLINDER faces touching y-max: {len(cyl_ymax)}")

    # Side with more sharp lines and fewer cylinders likely missing radii
    score_ymin = len(sharp_ymin) - len(cyl_ymin)
    score_ymax = len(sharp_ymax) - len(cyl_ymax)

    if score_ymin == score_ymax:
        # If ambiguous, still pick y-min by default ("left side" often corresponds to one side view)
        target_y = ymin
        other_y = ymax
        print("Y-side detection: tie; defaulting to y-min as target side")
    else:
        target_y = ymin if score_ymin > score_ymax else ymax
        other_y = ymax if target_y == ymin else ymin
        print(f"Y-side detection: target_y={target_y:.3f} other_y={other_y:.3f}")

    # ---- Infer reference radius from the opposite side's existing rounded cylinders in head region ----
    r_candidates = []
    for f in head_cyl_faces_touching_y(other_y):
        r = face_radius(f)
        if r is None or not isfinite(r):
            continue
        if 1.0 <= r <= 120.0:
            r_candidates.append(r)

    if not r_candidates:
        # fallback: any cylinder in head region that also touches an outer plane
        for f in faces0:
            if not is_cylinder_face(f):
                continue
            c = fcenter(f)
            if c.x > head_xmax or c.x > (shoulder_x - 5.0):
                continue
            fb = f.BoundingBox()
            if (
                touches_plane(fb.ymin, fb.ymax, ymin, tolY)
                or touches_plane(fb.ymin, fb.ymax, ymax, tolY)
                or touches_plane(fb.zmin, fb.zmax, zmin, tolZ)
                or touches_plane(fb.zmin, fb.zmax, zmax, tolZ)
                or touches_plane(fb.xmin, fb.xmax, xmin, tolX)
            ):
                r = face_radius(f)
                if r is None or not isfinite(r):
                    continue
                if 1.0 <= r <= 120.0:
                    r_candidates.append(r)

    r_candidates.sort()
    ref_r = r_candidates[-1] if r_candidates else 30.0
    ref_r = float(max(1.0, min(80.0, ref_r)))

    print(f"Reference fillet radius inferred: {ref_r:.3f} (candidates={r_candidates})")

    # ---- Candidate edges on target side of head that appear sharp (LINE) and on exterior ----
    # Focus on edges that touch the target y plane AND also touch an outer z/x plane (corner/perimeter)
    cand_pts = []
    cand_edges = []

    for e in edges0:
        if not is_line(e):
            continue
        c = ecenter(e)
        if c.x > head_xmax or c.x > (shoulder_x - 5.0):
            continue
        eb = e.BoundingBox()
        if not touches_plane(eb.ymin, eb.ymax, target_y, tolY):
            continue
        # exterior-ish: touches x-min or z-min or z-max
        if not (
            touches_plane(eb.xmin, eb.xmax, xmin, tolX)
            or touches_plane(eb.zmin, eb.zmax, zmin, tolZ)
            or touches_plane(eb.zmin, eb.zmax, zmax, tolZ)
        ):
            continue
        try:
            if e.Length() < max(3.0, 0.25 * ref_r):
                continue
        except Exception:
            pass
        cand_edges.append(e)
        cand_pts.append(ecenter(e))

    print(f"Candidate sharp edges to fillet on target y-side: {len(cand_edges)}")

    # If no edges found (selection too strict), broaden to any sharp line edges in head region touching x-min
    if not cand_pts:
        print("No y-side candidates found; broadening selection to x-min perimeter in head")
        for e in edges0:
            if not is_line(e):
                continue
            c = ecenter(e)
            if c.x > head_xmax or c.x > (shoulder_x - 5.0):
                continue
            eb = e.BoundingBox()
            if not touches_plane(eb.xmin, eb.xmax, xmin, tolX):
                continue
            try:
                if e.Length() < max(3.0, 0.25 * ref_r):
                    continue
            except Exception:
                pass
            cand_pts.append(ecenter(e))

        print(f"Candidate sharp edges to fillet on x-min: {len(cand_pts)}")

    if not cand_pts:
        print("No candidate edges found; returning original solid")
        return cq.Workplane(obj=main)

    # ---- Apply fillets sequentially (more robust than one-shot) ----
    def find_matching_edge(shape, pt):
        best = None
        best_d2 = None
        for e in shape.Edges():
            if not is_line(e):
                continue
            c = ecenter(e)
            if c.x > head_xmax or c.x > (shoulder_x - 5.0):
                continue
            # keep on same target side if possible
            eb = e.BoundingBox()
            if touches_plane(eb.ymin, eb.ymax, target_y, tolY):
                pass
            else:
                # allow x-min fallback only if nothing else matches, handled by distance anyway
                if not touches_plane(eb.xmin, eb.xmax, xmin, tolX):
                    continue
            dx = c.x - pt.x
            dy = c.y - pt.y
            dz = c.z - pt.z
            d2 = dx * dx + dy * dy + dz * dz
            if best is None or d2 < best_d2:
                best = e
                best_d2 = d2
        return best

    # de-duplicate target points (rounded key)
    uniq = {}
    for p in cand_pts:
        key = (round(p.x, 2), round(p.y, 2), round(p.z, 2))
        uniq[key] = p
    cand_pts = list(uniq.values())

    shape = main
    applied = 0
    failed = 0

    for i, pt in enumerate(cand_pts):
        e = find_matching_edge(shape, pt)
        if e is None:
            failed += 1
            continue
        try:
            wp = cq.Workplane(obj=shape).newObject([e]).fillet(ref_r)
            shape_new = wp.val()
            if hasattr(shape_new, "isValid") and not shape_new.isValid():
                raise ValueError("invalid solid after fillet")
            shape = shape_new
            applied += 1
        except Exception as ex:
            failed += 1
            # continue trying other edges

    print(f"Sequential fillet results: applied={applied}, failed={failed}, radius={ref_r:.3f}")

    # If we didn't manage to apply any fillet with the reference radius, do NOT downgrade the radius:
    # requirement is to match the other side.
    if applied == 0:
        print("No fillets could be applied with reference radius; leaving model unchanged to avoid incorrect radius")
        return cq.Workplane(obj=main)

    return cq.Workplane(obj=shape)
