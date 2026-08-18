def my_cad_function(args):
    import cadquery as cq
    import os
    import math

    input_file = os.path.expanduser(args.get('input_file', ''))
    shape_wp = cq.importers.importStep(input_file)
    root_shape = shape_wp.val() if hasattr(shape_wp, 'val') else shape_wp

    wp_root = cq.Workplane(obj=root_shape)
    solids = wp_root.solids().vals()
    print(f"Loaded STEP: {input_file}")
    print(f"Total solids found: {len(solids)}")
    if not solids:
        print("ERROR: No solids found")
        return shape_wp

    def bb_tuple(bb):
        return (bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax)

    # --- identify heatsink (S2) ---
    def score_heatsink(s):
        bb = s.BoundingBox()
        score = 0.0
        score += 6.0 if bb.xmax > 50 else 0.0
        score += 4.0 if bb.xmin > 10 else 0.0
        score += 4.0 if (bb.ymin < -14 and bb.ymax > -2) else 0.0
        score += 4.0 if (25 < bb.zmax < 40) else 0.0
        score += 2.0 if (bb.xlen > 20 and bb.ylen > 10 and bb.zlen > 20) else 0.0
        score -= 6.0 if bb.zmax > 45 else 0.0
        return score

    scored_hs = [(i, score_heatsink(s), s) for i, s in enumerate(solids)]
    scored_hs.sort(key=lambda t: t[1], reverse=True)
    for i, sc, s in scored_hs:
        print(f"Solid {i}: heatsinkScore={sc:.2f} bb={bb_tuple(s.BoundingBox())}")

    hs_idx, hs_score, hs_solid = scored_hs[0]
    if hs_score <= 0:
        print("WARNING: Could not confidently identify heatsink solid; returning original")
        return shape_wp

    hs_bb = hs_solid.BoundingBox()
    print(f"Selected heatsink solid index: {hs_idx} (score={hs_score:.2f})")
    print(f"Heatsink bbox: {bb_tuple(hs_bb)}")

    # --- identify aqua/manifold (S1) candidate to copy pattern from ---
    def score_aqua(s):
        bb = s.BoundingBox()
        score = 0.0
        score += 6.0 if bb.xmin < -40 else 0.0
        score += 3.0 if bb.xmax < 0 else 0.0
        score += 4.0 if (bb.ymin < -18 and bb.ymax > -2) else 0.0
        score += 3.0 if (20 < bb.zmax < 35) else 0.0
        score += 2.0 if (bb.xlen > 20 and bb.ylen > 10 and bb.zlen > 15) else 0.0
        return score

    scored_aq = [(i, score_aqua(s), s) for i, s in enumerate(solids) if i != hs_idx]
    scored_aq.sort(key=lambda t: t[1], reverse=True)
    aq_solid = None
    if scored_aq and scored_aq[0][1] > 0:
        aq_idx, aq_score, aq_solid = scored_aq[0]
        print(f"Selected aqua/manifold candidate index: {aq_idx} (score={aq_score:.2f}) bb={bb_tuple(aq_solid.BoundingBox())}")
    else:
        print("WARNING: Could not confidently identify aqua/manifold candidate")

    # --- helpers ---
    def wire_circle_data(w):
        edges = w.Edges()
        circ = [e for e in edges if hasattr(e, 'geomType') and e.geomType() == 'CIRCLE']
        if not circ:
            return None
        centers, radii = [], []
        for e in circ:
            try:
                centers.append(e.arcCenter())
                radii.append(e.radius())
            except Exception:
                pass
        if not radii:
            return None
        rmin, rmax = min(radii), max(radii)
        # allow small tolerance for segmented circles
        if (rmax - rmin) > 0.25:
            return None
        cx = sum(v.x for v in centers) / len(centers)
        cy = sum(v.y for v in centers) / len(centers)
        cz = sum(v.z for v in centers) / len(centers)
        rmean = sum(radii) / len(radii)
        return (cq.Vector(cx, cy, cz), rmean)

    def planar_face_hole_circles(solid, face_sel):
        wp = cq.Workplane(obj=solid)
        face = wp.faces(face_sel).val()
        wires = list(face.Wires())
        if not wires:
            return face, []
        # choose outer wire by bbox area in XZ
        def area_xz(w):
            bb = w.BoundingBox()
            return bb.xlen * bb.zlen
        outer = max(wires, key=area_xz)
        inner = [w for w in wires if w is not outer]
        circles = []
        for w in inner:
            cd = wire_circle_data(w)
            if cd:
                circles.append(cd)
        return face, circles

    def cluster_1d(vals, tol=0.8):
        if not vals:
            return []
        vals = sorted(vals)
        clusters = [[vals[0]]]
        for v in vals[1:]:
            cmean = sum(clusters[-1]) / len(clusters[-1])
            if abs(v - cmean) <= tol:
                clusters[-1].append(v)
            else:
                clusters.append([v])
        return [sum(c) / len(c) for c in clusters]

    def dedupe_centers(cr, tol=0.6):
        # cr: list of (centerVec, radius)
        out = []
        for c, r in cr:
            keep = True
            for c2, r2 in out:
                if (c - c2).Length < tol and abs(r - r2) < 0.4:
                    keep = False
                    break
            if keep:
                out.append((c, r))
        return out

    def hole_like_y_cylinders(solid, near_y, hs_bb_local, rmin=1.0, rmax=3.5, ytol=0.25):
        # Detect cylindrical faces with axis approximately along Y (so XZ bbox ~ circle),
        # and starting at (or very near) a given planar y.
        cyls = cq.Workplane(obj=solid).faces('%CYLINDER').vals()
        hits = []
        for f in cyls:
            bb = f.BoundingBox()
            # axis ~Y => ylen significantly larger than xlen and zlen, and xlen ~ zlen
            if bb.ylen < 2.0:
                continue
            if abs(bb.xlen - bb.zlen) > 0.8:
                continue
            r = 0.5 * min(bb.xlen, bb.zlen)
            if not (rmin <= r <= rmax):
                continue
            # near face plane
            if abs(bb.ymin - near_y) <= ytol or abs(bb.ymax - near_y) <= ytol:
                cx = 0.5 * (bb.xmin + bb.xmax)
                cy = 0.5 * (bb.ymin + bb.ymax)
                cz = 0.5 * (bb.zmin + bb.zmax)
                hits.append((cq.Vector(cx, cy, cz), r))
        return dedupe_centers(hits)

    def best_mount_face_for_solid(solid):
        bb = solid.BoundingBox()
        # compare <Y vs >Y using wire-circles and cylinder heuristics
        f_min, cir_min = planar_face_hole_circles(solid, '<Y')
        f_max, cir_max = planar_face_hole_circles(solid, '>Y')
        y_min = bb.ymin
        y_max = bb.ymax
        cyl_min = hole_like_y_cylinders(solid, y_min, bb)
        cyl_max = hole_like_y_cylinders(solid, y_max, bb)

        # count small holes in radius band
        def count_mount(cirs):
            return len([(c, r) for (c, r) in cirs if 1.0 <= r <= 3.5])

        score_min = count_mount(cir_min) + len(cyl_min)
        score_max = count_mount(cir_max) + len(cyl_max)

        print(f"Mount-face probe: <Y wires={len(cir_min)} mount={count_mount(cir_min)} cylHits={len(cyl_min)} score={score_min}")
        print(f"Mount-face probe: >Y wires={len(cir_max)} mount={count_mount(cir_max)} cylHits={len(cyl_max)} score={score_max}")

        if score_max > score_min:
            return '>Y', f_max, cir_max, y_max
        else:
            return '<Y', f_min, cir_min, y_min

    # --- determine which heatsink face is the actual mounting/back face ---
    hs_face_sel, hs_face, hs_face_circles, hs_face_y = best_mount_face_for_solid(hs_solid)
    thickness_y = hs_bb.ylen
    print(f"Selected heatsink mounting face: {hs_face_sel} at y~{hs_face_y:.3f} thickness_y={thickness_y:.3f}")

    # --- measure aqua pattern (dx, dz, r) from its likely mounting face ---
    aqua_dx = aqua_dz = None
    aqua_r = None
    if aq_solid is not None:
        aq_face_sel, aq_face, aq_circles, aq_face_y = best_mount_face_for_solid(aq_solid)
        aq_bb = aq_solid.BoundingBox()
        aq_circles = [(c, r) for (c, r) in dedupe_centers(aq_circles) if 1.0 <= r <= 3.5]

        # derive 2x2 spacing if possible
        if len(aq_circles) >= 4:
            xs = [c.x for c, r in aq_circles]
            zs = [c.z for c, r in aq_circles]
            xcl = cluster_1d(xs, tol=0.9)
            zcl = cluster_1d(zs, tol=0.9)
            if len(xcl) >= 2 and len(zcl) >= 2:
                xcl = sorted(xcl)[:2] if len(xcl) > 2 else sorted(xcl)
                zcl = sorted(zcl)[:2] if len(zcl) > 2 else sorted(zcl)
                aqua_dx = abs(xcl[-1] - xcl[0])
                aqua_dz = abs(zcl[-1] - zcl[0])
                aqua_r = sorted([r for c, r in aq_circles])[len(aq_circles)//2]

        print(f"Aqua mounting face selected: {aq_face_sel} at y~{aq_face_y:.3f}")
        print(f"Aqua mount inference: dx={aqua_dx} dz={aqua_dz} r~{aqua_r}")

    # defaults if aqua extraction fails
    if aqua_dx is None:
        aqua_dx = min(14.0, hs_bb.xlen * 0.5)
    if aqua_dz is None:
        aqua_dz = min(16.0, hs_bb.zlen * 0.55)
    if aqua_r is None:
        aqua_r = 1.7

    # hole feature sizes
    clear_d = max(3.0, min(4.5, 2.0 * aqua_r + 0.2))
    cbore_d = max(5.5, min(9.0, clear_d * 2.0))
    cbore_depth = 3.0

    # --- find big vertical (Z-axis) bores in heatsink for keepout in X ---
    cyl_faces = cq.Workplane(obj=hs_solid).faces('%CYLINDER').vals()
    bore_candidates = []
    for f in cyl_faces:
        bb = f.BoundingBox()
        # vertical along Z => zlen large, xlen~ylen (circle in XY)
        if bb.zlen > 0.6 * hs_bb.zlen and abs(bb.xlen - bb.ylen) < 0.8 and (min(bb.xlen, bb.ylen) > 4.0):
            r = 0.5 * min(bb.xlen, bb.ylen)
            cx = 0.5 * (bb.xmin + bb.xmax)
            cy = 0.5 * (bb.ymin + bb.ymax)
            bore_candidates.append((r, cx, cy, bb))
    bore_candidates.sort(reverse=True, key=lambda t: t[0])
    big_bores = bore_candidates[:2]
    if big_bores:
        print("Detected big vertical bores (keepout reference):")
        for r, cx, cy, bb in big_bores:
            print(f"  bore r~{r:.3f} centerX~{cx:.3f} centerY~{cy:.3f}")

    # --- compute symmetric 2x2 positions on heatsink mounting face, using aqua dx/dz, with edge + bore keepout ---
    xmid = 0.5 * (hs_bb.xmin + hs_bb.xmax)
    zmid = 0.5 * (hs_bb.zmin + hs_bb.zmax)

    # enforce minimum edge distance
    min_edge = max(4.0, clear_d * 1.25)

    # initial desired half-spans
    hx = 0.5 * aqua_dx
    hz = 0.5 * aqua_dz

    # clamp to fit within edges
    hx = min(hx, (hs_bb.xlen * 0.5) - min_edge)
    hz = min(hz, (hs_bb.zlen * 0.5) - min_edge)
    hx = max(hx, 3.0)
    hz = max(hz, 3.0)

    # bore keepout band in X
    r_mount = 0.5 * clear_d
    margin = 1.0
    x_allowed_min = hs_bb.xmin + min_edge
    x_allowed_max = hs_bb.xmax - min_edge

    if len(big_bores) == 2:
        bores = sorted([(cx, r) for (r, cx, cy, bb) in big_bores], key=lambda t: t[0])
        (c1, r1), (c2, r2) = bores
        k1 = r1 + r_mount + margin
        k2 = r2 + r_mount + margin
        band_lo = max(x_allowed_min, c1 + k1)
        band_hi = min(x_allowed_max, c2 - k2)
        if band_lo < band_hi:
            band_mid = 0.5 * (band_lo + band_hi)
            band_half = 0.5 * (band_hi - band_lo)
            # shrink hx if needed
            hx = min(hx, band_half * 0.9)
            xmid = band_mid
            print(f"X keepout band used: [{band_lo:.3f}, {band_hi:.3f}] -> xmid={xmid:.3f} hx={hx:.3f}")
        else:
            print(f"WARNING: No feasible x band between bores. band_lo={band_lo:.3f} band_hi={band_hi:.3f}. Proceeding without band centering.")

    x_low, x_high = xmid - hx, xmid + hx
    z_low, z_high = zmid - hz, zmid + hz

    # final clamp to edges
    x_low = max(x_low, x_allowed_min)
    x_high = min(x_high, x_allowed_max)
    z_low = max(z_low, hs_bb.zmin + min_edge)
    z_high = min(z_high, hs_bb.zmax - min_edge)

    print("Heatsink new 4-hole pattern (symmetric, global coords):")
    print(f"  x_low={x_low:.3f} x_high={x_high:.3f} z_low={z_low:.3f} z_high={z_high:.3f}")
    print(f"  hole clear_d={clear_d:.3f} cbore_d={cbore_d:.3f} cbore_depth={cbore_depth:.3f}")

    # --- plug legacy 3-hole pattern if present on the selected mounting face ---
    hs_face_circles = dedupe_centers(hs_face_circles)
    legacy = [(c, r) for (c, r) in hs_face_circles if 1.0 <= r <= 3.5]
    print(f"Heatsink mount-face openings (wire-circles) in legacy range: {len(legacy)}")

    hs_wp0 = cq.Workplane(obj=hs_solid)
    mount_wp0 = hs_wp0.faces(hs_face_sel).workplane(centerOption='CenterOfBoundBox')
    plane0 = mount_wp0.plane

    hs_after_plug = cq.Workplane(obj=hs_solid)
    if len(legacy) == 3:
        print("Legacy 3-hole pattern detected on heatsink mounting face -> plugging")
        plug_depth = thickness_y + 2.0
        plug_solids = []
        for c3d, r in legacy:
            lp = plane0.toLocalCoords(c3d)
            plug = mount_wp0.center(lp.x, lp.y).circle(r * 1.02).extrude(-plug_depth, combine=False)
            plug_solids.append(plug.val())
        plugs = plug_solids[0]
        for ps in plug_solids[1:]:
            plugs = plugs.fuse(ps)
        hs_after_plug = cq.Workplane(obj=hs_solid).union(plugs)
    else:
        if len(legacy) > 0:
            print("NOTE: Mount-face holes exist but count != 3; leaving them unchanged (cannot safely assume legacy pattern).")
        else:
            # try cylinder-based legacy detection
            y_ref = hs_bb.ymin if hs_face_sel == '<Y' else hs_bb.ymax
            cyl_legacy = hole_like_y_cylinders(hs_solid, y_ref, hs_bb, rmin=1.0, rmax=3.5)
            print(f"Heatsink mount-face cylinder-based small-hole hits: {len(cyl_legacy)}")
            if len(cyl_legacy) == 3:
                print("Legacy 3-hole pattern inferred from cylinders -> plugging")
                plug_depth = thickness_y + 2.0
                plug_solids = []
                for c3d, r in cyl_legacy:
                    lp = plane0.toLocalCoords(c3d)
                    plug = mount_wp0.center(lp.x, lp.y).circle(r * 1.02).extrude(-plug_depth, combine=False)
                    plug_solids.append(plug.val())
                plugs = plug_solids[0]
                for ps in plug_solids[1:]:
                    plugs = plugs.fuse(ps)
                hs_after_plug = cq.Workplane(obj=hs_solid).union(plugs)

    hs_plugged_solid = hs_after_plug.val() if hasattr(hs_after_plug, 'val') else hs_after_plug

    # --- cut the new 4 counterbored through holes on the selected mounting face ---
    hs_wp1 = cq.Workplane(obj=hs_plugged_solid)
    mount_wp1 = hs_wp1.faces(hs_face_sel).workplane(centerOption='CenterOfBoundBox')
    plane1 = mount_wp1.plane

    centers_global = [
        cq.Vector(x_low, hs_face_y, z_low),
        cq.Vector(x_high, hs_face_y, z_low),
        cq.Vector(x_low, hs_face_y, z_high),
        cq.Vector(x_high, hs_face_y, z_high),
    ]

    pts2d = []
    for p in centers_global:
        lp = plane1.toLocalCoords(p)
        pts2d.append((lp.x, lp.y))

    hs_modified_wp = mount_wp1.pushPoints(pts2d).cboreHole(clear_d, cbore_d, cbore_depth, depth=thickness_y + 2.0)
    hs_modified_solid = hs_modified_wp.val() if hasattr(hs_modified_wp, 'val') else hs_modified_wp

    # quick post-check: how many openings now visible on that face?
    try:
        _, cir_post = planar_face_hole_circles(hs_modified_solid, hs_face_sel)
        cir_post = [(c, r) for (c, r) in dedupe_centers(cir_post) if 1.0 <= r <= 3.5]
        print(f"Post-check: mount-face openings (wire-circles) in 1..3.5r range: {len(cir_post)}")
    except Exception as e:
        print(f"Post-check warning: {e}")

    # --- rebuild compound swapping modified heatsink back into assembly ---
    new_solids = []
    for i, s in enumerate(solids):
        new_solids.append(hs_modified_solid if i == hs_idx else s)

    result = cq.Compound.makeCompound(new_solids)
    print("Finished mounting update (mount face auto-detected, legacy plugging conditional).")
    return result
