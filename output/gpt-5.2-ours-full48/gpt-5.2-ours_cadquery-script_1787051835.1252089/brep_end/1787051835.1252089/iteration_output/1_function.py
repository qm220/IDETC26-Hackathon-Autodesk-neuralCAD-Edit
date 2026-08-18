def my_cad_function(args):
    import cadquery as cq
    import os
    from math import isfinite

    input_file = os.path.expanduser(args.get('input_file', ''))
    if not input_file or not os.path.exists(input_file):
        raise ValueError(f"Missing or invalid args['input_file']: {input_file}")

    wp_in = cq.importers.importStep(input_file)

    # --- Extract solids/wires from imported shape; operate only on the largest solid ---
    root = wp_in.val() if hasattr(wp_in, 'val') else wp_in

    def all_solids(shape):
        try:
            return list(shape.Solids())
        except Exception:
            return []

    def all_wires(shape):
        try:
            return list(shape.Wires())
        except Exception:
            return []

    def all_edges(shape):
        try:
            return list(shape.Edges())
        except Exception:
            return []

    solids = all_solids(root)
    if not solids:
        # Fallback: some STEP files import as a single solid already
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

    # Keep other geometry (e.g. lanyard curve) untouched
    other_shapes = []
    # include wires/edges not part of main solid if present
    try:
        # if root is a compound, collect wires from it
        for w in all_wires(root):
            other_shapes.append(w)
    except Exception:
        pass

    bb = main.BoundingBox()
    xmin, xmax = bb.xmin, bb.xmax
    ymin, ymax = bb.ymin, bb.ymax
    zmin, zmax = bb.zmin, bb.zmax
    xlen, ylen, zlen = bb.xlen, bb.ylen, bb.zlen
    ymid = 0.5 * (ymin + ymax)

    print(f"MAIN BBOX: x[{xmin:.3f},{xmax:.3f}] y[{ymin:.3f},{ymax:.3f}] z[{zmin:.3f},{zmax:.3f}]")

    # Head/big-body region heuristic: left portion of the model
    head_xmax = xmin + 0.42 * xlen
    # Exclude far right interface/nose
    x_cut_nose = xmin + 0.90 * xlen

    tolY = max(0.5, 0.015 * ylen)
    tolX = max(0.5, 0.015 * xlen)

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
            return e.geomType() == 'LINE'
        except Exception:
            return False

    def is_cylinder_face(f):
        try:
            return f.geomType() == 'CYLINDER'
        except Exception:
            return False

    def face_radius(f):
        try:
            return float(f.radius())
        except Exception:
            return None

    def touches_plane_y(bb_obj, yval, tol):
        return (abs(bb_obj.ymin - yval) <= tol) or (abs(bb_obj.ymax - yval) <= tol)

    def touches_plane_x(bb_obj, xval, tol):
        return (abs(bb_obj.xmin - xval) <= tol) or (abs(bb_obj.xmax - xval) <= tol)

    # --- Diagnose which 'side' is missing radii (prefer y-sides, then x-min) ---
    edges = list(main.Edges())
    faces = list(main.Faces())

    def sharp_line_edges_on_y(side_y):
        out = []
        for e in edges:
            if not is_line(e):
                continue
            c = ecenter(e)
            if c.x > head_xmax:  # only big left body
                continue
            eb = e.BoundingBox()
            if not touches_plane_y(eb, side_y, tolY):
                continue
            try:
                if e.Length() < 2.0:
                    continue
            except Exception:
                pass
            out.append(e)
        return out

    def cyl_faces_touching_y(side_y):
        out = []
        for f in faces:
            c = fcenter(f)
            if c.x > head_xmax:
                continue
            if not is_cylinder_face(f):
                continue
            fb = f.BoundingBox()
            if touches_plane_y(fb, side_y, tolY):
                out.append(f)
        return out

    sharp_ymin = sharp_line_edges_on_y(ymin)
    sharp_ymax = sharp_line_edges_on_y(ymax)
    cyl_ymin = cyl_faces_touching_y(ymin)
    cyl_ymax = cyl_faces_touching_y(ymax)

    print(f"Head-region sharp LINE edges: ymin={len(sharp_ymin)} ymax={len(sharp_ymax)}")
    print(f"Head-region CYLINDER faces touching side: ymin={len(cyl_ymin)} ymax={len(cyl_ymax)}")

    # score: more sharp lines and fewer cylinders => more likely missing fillets
    score_ymin = len(sharp_ymin) - len(cyl_ymin)
    score_ymax = len(sharp_ymax) - len(cyl_ymax)

    target_mode = None
    if score_ymin != score_ymax:
        target_mode = 'y'
        target_y = ymin if score_ymin > score_ymax else ymax
        other_y = ymax if target_y == ymin else ymin
    else:
        # Tie: likely not a y-side issue; try x-min ("left") end of the big body
        target_mode = 'x'
        target_x = xmin

    print(f"Chosen targeting mode: {target_mode}")

    # --- Infer reference radius from the already-rounded 'other side' ---
    inferred_r = None

    if target_mode == 'y':
        # Use largest external cylinder radius touching the opposite y-side in head region
        candidates = []
        for f in cyl_faces_touching_y(other_y):
            r = face_radius(f)
            if r is None or not isfinite(r):
                continue
            if 1.0 <= r <= 120.0:
                candidates.append(r)
        candidates.sort()
        if candidates:
            inferred_r = candidates[-1]
        print(f"Inferred radius from opposite y-side cylinders: {inferred_r} (candidates={candidates})")

    if inferred_r is None:
        # Fallback: use largest cylinder radius anywhere on head region (external-ish)
        candidates = []
        for f in faces:
            if not is_cylinder_face(f):
                continue
            c = fcenter(f)
            if c.x > head_xmax:
                continue
            r = face_radius(f)
            if r is None or not isfinite(r):
                continue
            fb = f.BoundingBox()
            # Prefer faces that reach outside y-extremes (likely external blends)
            if touches_plane_y(fb, ymin, tolY) or touches_plane_y(fb, ymax, tolY) or touches_plane_x(fb, xmin, tolX):
                if 1.0 <= r <= 120.0:
                    candidates.append(r)
        candidates.sort()
        inferred_r = candidates[-1] if candidates else 30.0
        print(f"Fallback inferred radius from head-region cylinders: {inferred_r} (candidates={candidates})")

    # Clamp to sane values
    inferred_r = float(max(1.0, min(80.0, inferred_r)))

    # --- Select target edges to fillet ---
    def candidate_edges_for_y(side_y):
        out = []
        for e in edges:
            if not is_line(e):
                continue
            c = ecenter(e)
            # only big part/head; also keep away from nose
            if c.x > head_xmax:
                continue
            if c.x > x_cut_nose:
                continue
            eb = e.BoundingBox()
            if not touches_plane_y(eb, side_y, tolY):
                continue
            # Exclude very small edges
            try:
                if e.Length() < max(2.0, 0.20 * inferred_r):
                    continue
            except Exception:
                pass
            out.append(e)
        return out

    def candidate_edges_for_xmin():
        out = []
        for e in edges:
            if not is_line(e):
                continue
            c = ecenter(e)
            if c.x > head_xmax:
                continue
            eb = e.BoundingBox()
            if not touches_plane_x(eb, xmin, tolX):
                continue
            try:
                if e.Length() < max(2.0, 0.20 * inferred_r):
                    continue
            except Exception:
                pass
            out.append(e)
        return out

    if target_mode == 'y':
        target_edges = candidate_edges_for_y(target_y)
        print(f"Target y-side={target_y:.3f}: candidate LINE edges to fillet: {len(target_edges)}")
    else:
        target_edges = candidate_edges_for_xmin()
        print(f"Target x-min={xmin:.3f}: candidate LINE edges to fillet: {len(target_edges)}")

    # If no candidates, do nothing but return original
    if not target_edges:
        print("No candidate edges found; returning original geometry")
        result_main = main
    else:
        # Try fillet with inferred radius; if fails, reduce slightly but keep near reference
        radii_to_try = [inferred_r, inferred_r * 0.95, inferred_r * 0.90, inferred_r * 0.85, inferred_r * 0.80]
        radii_to_try = [float(max(1.0, r)) for r in radii_to_try]

        result_main = None
        last_err = None

        for r in radii_to_try:
            try:
                res_wp = cq.Workplane(obj=main).newObject(target_edges).fillet(r)
                candidate = res_wp.val()
                if hasattr(candidate, 'isValid') and not candidate.isValid():
                    raise ValueError("Fillet produced invalid solid")
                print(f"Applied fillet R={r:.3f} to {len(target_edges)} edges (single-shot)")
                result_main = candidate
                break
            except Exception as e:
                last_err = e
                print(f"Fillet failed for R={r:.3f}: {e}")

        if result_main is None:
            # As a last resort, do a conservative fillet with a smaller radius.
            # (We keep this as a fallback, but it may not meet the 'same radius' requirement.)
            conservative_r = max(1.0, inferred_r * 0.60)
            print(f"All near-reference radii failed; trying conservative R={conservative_r:.3f}")
            try:
                res_wp = cq.Workplane(obj=main).newObject(target_edges).fillet(conservative_r)
                result_main = res_wp.val()
            except Exception as e:
                raise RuntimeError(f"Unable to apply fillet to target edges. Last error: {last_err}; conservative also failed: {e}")

    # Recombine with other shapes (wires, etc.) if they exist
    try:
        if other_shapes:
            comp = cq.Compound.makeCompound([result_main] + other_shapes)
            return cq.Workplane(obj=comp)
    except Exception:
        pass

    return cq.Workplane(obj=result_main)
