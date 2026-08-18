def my_cad_function(args):
    import cadquery as cq
    import os
    from collections import defaultdict

    # --- helpers ---
    def solids_from(shape):
        try:
            return list(shape.Solids())
        except Exception:
            try:
                return list(cq.Workplane(obj=shape).solids().vals())
            except Exception:
                return []

    def biggest_solid(shape):
        sols = solids_from(shape)
        if not sols:
            return None
        return max(sols, key=lambda s: float(s.Volume()))

    input_file = os.path.expanduser(args.get("input_file", ""))
    if not input_file or not os.path.exists(input_file):
        raise ValueError(f"Missing or invalid args['input_file']: {input_file}")

    imported = cq.importers.importStep(input_file)
    if hasattr(imported, "toCompound") and not hasattr(imported, "val"):
        root = imported.toCompound()
    else:
        root = imported.val() if hasattr(imported, "val") else imported

    main = biggest_solid(root)
    if main is None:
        raise ValueError("No solids found in imported STEP")

    bb = main.BoundingBox()
    xmin, xmax = bb.xmin, bb.xmax
    ymin, ymax = bb.ymin, bb.ymax
    zmin, zmax = bb.zmin, bb.zmax
    xlen, ylen, zlen = bb.xlen, bb.ylen, bb.zlen

    print(f"MAIN BBOX: x[{xmin:.3f},{xmax:.3f}] y[{ymin:.3f},{ymax:.3f}] z[{zmin:.3f},{zmax:.3f}]")

    # Head is on x-min side; keep cutoff before the pocket region (pocket starts ~x=125 per planning)
    head_x_cut = xmin + min(105.0, 0.40 * xlen)
    tol = max(0.25, 0.004 * max(xlen, ylen, zlen))
    tolY = max(0.5, 0.02 * ylen)

    def edge_center(e):
        try:
            return e.Center()
        except Exception:
            return e.centerOfMass()

    def edge_bb(e):
        return e.BoundingBox()

    def is_line_edge(e):
        try:
            return e.geomType() == "LINE"
        except Exception:
            return False

    def in_head_region(e):
        c = edge_center(e)
        return c.x <= head_x_cut + tol

    def near_y_side(e, yside):
        eb = edge_bb(e)
        return abs(eb.ymin - yside) <= tolY or abs(eb.ymax - yside) <= tolY

    def on_outer_extents(e):
        eb = edge_bb(e)
        # outer edges will touch at least one global extent
        return (
            abs(eb.xmin - xmin) <= tol or abs(eb.xmax - xmax) <= tol or
            abs(eb.ymin - ymin) <= tol or abs(eb.ymax - ymax) <= tol or
            abs(eb.zmin - zmin) <= tol or abs(eb.zmax - zmax) <= tol
        )

    # Determine which Y side has more sharp (line) edges in the head region -> likely missing radii
    edges_all = list(main.Edges())

    def sharp_edge_count_at_side(yside):
        cnt = 0
        for e in edges_all:
            if not is_line_edge(e):
                continue
            if not in_head_region(e):
                continue
            if not near_y_side(e, yside):
                continue
            if not on_outer_extents(e):
                continue
            cnt += 1
        return cnt

    cnt_ymin = sharp_edge_count_at_side(ymin)
    cnt_ymax = sharp_edge_count_at_side(ymax)
    bad_side = ymax if cnt_ymax >= cnt_ymin else ymin
    good_side = ymin if bad_side == ymax else ymax

    print(f"Sharp (LINE) edge count near y={ymin:.3f}: {cnt_ymin}")
    print(f"Sharp (LINE) edge count near y={ymax:.3f}: {cnt_ymax}")
    print(f"Assuming missing-radii side is y={bad_side:.3f} (good side y={good_side:.3f})")

    # Estimate reference radius from existing cylindrical faces on the good side (head region)
    r_ref = 30.0
    radii_bins = defaultdict(float)  # bin -> total area

    try:
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.GeomAbs import GeomAbs_Cylinder

        for f in main.Faces():
            fb = f.BoundingBox()
            fc = f.Center()
            if fc.x > head_x_cut + 2 * tol:
                continue
            # must be near the good y side
            if not (abs(fb.ymin - good_side) <= tolY or abs(fb.ymax - good_side) <= tolY):
                continue
            try:
                ad = BRepAdaptor_Surface(f.wrapped)
                if ad.GetType() != GeomAbs_Cylinder:
                    continue
                r = float(ad.Cylinder().Radius())
                if r < 5 or r > 80:
                    continue
                a = float(f.Area())
                # bin by 0.5mm to get stable clustering
                b = round(r * 2.0) / 2.0
                radii_bins[b] += a
            except Exception:
                continue

        if radii_bins:
            # pick bin with largest area, prefer "large" radii typical of the head (>=10)
            candidates = [(b, a) for b, a in radii_bins.items() if b >= 10.0]
            if candidates:
                candidates.sort(key=lambda t: t[1], reverse=True)
                r_ref = float(candidates[0][0])
    except Exception as ex:
        print(f"Radius detection failed, using fallback r_ref=30.0; reason: {ex}")

    print(f"Using reference fillet radius r_ref={r_ref:.3f}")

    # Build fillet selection predicates
    def candidate_edge(e):
        if not is_line_edge(e):
            return False
        if not in_head_region(e):
            return False
        if not near_y_side(e, bad_side):
            return False
        if not on_outer_extents(e):
            return False
        # Avoid the head-to-arm shoulder/interface by staying close to the left end
        # (keeps from changing functional shoulder at ~x=100)
        c = edge_center(e)
        return c.x <= (xmin + 95.0 + tol)

    def candidate_end_face_edge(e):
        if not candidate_edge(e):
            return False
        eb = edge_bb(e)
        # edges lying on the left end face plane (x ~ xmin)
        return abs(eb.xmin - xmin) <= tol and abs(eb.xmax - xmin) <= tol

    def candidate_non_end_edge(e):
        return candidate_edge(e) and (not candidate_end_face_edge(e))

    # CadQuery selector wrapper
    from cadquery import selectors

    class PredSelector(selectors.Selector):
        def __init__(self, pred):
            self.pred = pred
        def filter(self, objectList):
            return [o for o in objectList if self.pred(o)]

    # Count selections
    n_end = len([e for e in edges_all if candidate_end_face_edge(e)])
    n_other = len([e for e in edges_all if candidate_non_end_edge(e)])
    print(f"Candidate edges to fillet on bad side: end-face={n_end}, other={n_other}")

    result = main

    # Apply fillets in two stages for robustness
    if n_end > 0:
        try:
            result = cq.Workplane(obj=result).edges(PredSelector(candidate_end_face_edge)).fillet(r_ref).val()
            print("Applied fillet to end-face perimeter edges.")
        except Exception as ex:
            print(f"End-face fillet failed: {ex}")

    if n_other > 0:
        try:
            result = cq.Workplane(obj=result).edges(PredSelector(candidate_non_end_edge)).fillet(r_ref).val()
            print("Applied fillet to remaining head-side edges.")
        except Exception as ex:
            print(f"Secondary head-edge fillet failed: {ex}")

    bb2 = result.BoundingBox()
    print(f"FINAL BBOX: x[{bb2.xmin:.3f},{bb2.xmax:.3f}] y[{bb2.ymin:.3f},{bb2.ymax:.3f}] z[{bb2.zmin:.3f},{bb2.zmax:.3f}]")

    return cq.Workplane(obj=result)
