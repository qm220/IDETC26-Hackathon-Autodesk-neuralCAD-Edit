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

    if len(solids) == 0:
        print("ERROR: No solids in STEP")
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
        score += 4.0 if (bb.zmax > 25 and bb.zmax < 40) else 0.0
        score += 2.0 if (bb.xlen > 20 and bb.ylen > 10 and bb.zlen > 20) else 0.0
        score -= 6.0 if bb.zmax > 45 else 0.0
        return score

    scored_hs = [(i, score_heatsink(s), s) for i, s in enumerate(solids)]
    scored_hs.sort(key=lambda t: t[1], reverse=True)
    for i, sc, s in scored_hs:
        bb = s.BoundingBox()
        print(f"Solid {i}: heatsinkScore={sc:.2f} bb={bb_tuple(bb)}")

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
        score += 3.0 if (bb.zmax > 20 and bb.zmax < 35) else 0.0
        score += 2.0 if (bb.xlen > 20 and bb.ylen > 10 and bb.zlen > 15) else 0.0
        return score

    scored_aq = [(i, score_aqua(s), s) for i, s in enumerate(solids) if i != hs_idx]
    scored_aq.sort(key=lambda t: t[1], reverse=True)
    aq_idx = None
    aq_solid = None
    if scored_aq and scored_aq[0][1] > 0:
        aq_idx, aq_score, aq_solid = scored_aq[0]
        aq_bb = aq_solid.BoundingBox()
        print(f"Selected aqua/manifold candidate index: {aq_idx} (score={aq_score:.2f}) bbox={bb_tuple(aq_bb)}")
    else:
        print("WARNING: Could not confidently identify aqua/manifold candidate; will use safe default pattern")

    # --- helpers: detect circular hole openings on a planar face via inner wires ---
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
        if (rmax - rmin) > 0.2:
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
        # choose outer wire (largest XZ bbox area)
        def area_xz(w):
            bb = w.BoundingBox()
            return bb.xlen * bb.zlen
        outer = max(wires, key=area_xz)
        inner = [w for w in wires if w is not outer]
        circles = []
        for w in inner:
            cd = wire_circle_data(w)
            if not cd:
                continue
            c3d, r = cd
            circles.append((c3d, r))
        return face, circles

    def cluster_vals(vals, tol=0.6):
        # simple 1D clustering by sorting
        if not vals:
            return []
        vals = sorted(vals)
        clusters = [[vals[0]]]
        for v in vals[1:]:
            if abs(v - sum(clusters[-1]) / len(clusters[-1])) <= tol:
                clusters[-1].append(v)
            else:
                clusters.append([v])
        return [sum(c) / len(c) for c in clusters]

    def pick_2x2_pattern(circles, bb, r_range=(1.0, 3.5)):
        # returns dict with x_low,x_high,z_low,z_high,r_median and offsets if detected
        cands = [(c, r) for (c, r) in circles if (r_range[0] <= r <= r_range[1])]
        if len(cands) < 4:
            return None

        xs = [c.x for c, r in cands]
        zs = [c.z for c, r in cands]
        rs = sorted([r for c, r in cands])
        r_med = rs[len(rs)//2]

        x_clusters = cluster_vals(xs, tol=0.8)
        z_clusters = cluster_vals(zs, tol=0.8)

        # If we don't have exactly 2x2 clusters, try selecting 4 corners based on bbox of centers
        if len(x_clusters) != 2 or len(z_clusters) != 2:
            xmin, xmax = min(xs), max(xs)
            zmin, zmax = min(zs), max(zs)
            targets = [(xmin, zmin), (xmax, zmin), (xmin, zmax), (xmax, zmax)]
            chosen = []
            used = set()
            for tx, tz in targets:
                best = None
                best_d = 1e9
                for idx, (c, r) in enumerate(cands):
                    if idx in used:
                        continue
                    d = (c.x - tx) ** 2 + (c.z - tz) ** 2
                    if d < best_d:
                        best_d = d
                        best = (idx, c, r)
                if best is not None:
                    used.add(best[0])
                    chosen.append((best[1], best[2]))
            if len(chosen) != 4:
                return None
            xs2 = [c.x for c, r in chosen]
            zs2 = [c.z for c, r in chosen]
            x_low, x_high = min(xs2), max(xs2)
            z_low, z_high = min(zs2), max(zs2)
        else:
            x_low, x_high = sorted(x_clusters)
            z_low, z_high = sorted(z_clusters)

        off_left = x_low - bb.xmin
        off_right = bb.xmax - x_high
        off_bottom = z_low - bb.zmin
        off_top = bb.zmax - z_high

        return {
            'x_low': x_low, 'x_high': x_high,
            'z_low': z_low, 'z_high': z_high,
            'r_med': r_med,
            'off_left': off_left, 'off_right': off_right,
            'off_bottom': off_bottom, 'off_top': off_top,
        }

    # --- measure aqua back mounting (try minY and maxY, take richer one) ---
    aqua_pattern = None
    if aq_solid is not None:
        aq_bb = aq_solid.BoundingBox()
        f1, cir1 = planar_face_hole_circles(aq_solid, '<Y')
        f2, cir2 = planar_face_hole_circles(aq_solid, '>Y')
        # Prefer face with more mount-sized circles
        p1 = pick_2x2_pattern(cir1, aq_bb)
        p2 = pick_2x2_pattern(cir2, aq_bb)
        if p1 and (not p2 or len(cir1) >= len(cir2)):
            aqua_pattern = p1
            aqua_face_sel = '<Y'
        elif p2:
            aqua_pattern = p2
            aqua_face_sel = '>Y'
        else:
            aqua_pattern = None
            aqua_face_sel = None

        print(f"Aqua hole detection: <Y circles={len(cir1)} ; >Y circles={len(cir2)} ; selectedFace={aqua_face_sel}")
        if aqua_pattern:
            print("Aqua 2x2 pattern (measured):")
            for k in ['off_left','off_right','off_bottom','off_top','r_med']:
                print(f"  {k} = {aqua_pattern[k]:.3f}")
        else:
            print("WARNING: Could not robustly extract a 2x2 mounting pattern from aqua block; will use safe default pattern")

    # --- heatsink: determine back face (per planning: y = minY) ---
    hs_wp = cq.Workplane(obj=hs_solid)
    back_face = hs_wp.faces('<Y').val()
    y_back = back_face.BoundingBox().ymin
    thickness_y = hs_bb.ymax - hs_bb.ymin
    print(f"Heatsink back face y_back={y_back:.3f}, thickness_y={thickness_y:.3f}")

    # --- attempt to detect and plug legacy holes on heatsink back face (3-point pattern) ---
    _, hs_back_circles = planar_face_hole_circles(hs_solid, '<Y')
    legacy = [(c, r) for (c, r) in hs_back_circles if 1.0 <= r <= 3.5]
    print(f"Heatsink back-face circular openings detected: total={len(hs_back_circles)} legacyRange={len(legacy)}")

    hs_base = cq.Workplane(obj=hs_solid)
    if len(legacy) == 3:
        print("Legacy 3-hole pattern detected on heatsink back face -> plugging before adding new 4-hole pattern")
        bf_wp = cq.Workplane(obj=back_face)
        plane = bf_wp.plane
        plug_solids = []
        for c3d, r in legacy:
            loc = plane.toLocalCoords(c3d)
            plug = bf_wp.center(loc.x, loc.y).circle(r * 1.01).extrude(-(thickness_y + 1.0), combine=False)
            plug_solids.append(plug.val())
        plugs = plug_solids[0]
        for ps in plug_solids[1:]:
            plugs = plugs.fuse(ps)
        hs_base = cq.Workplane(obj=hs_solid).union(plugs)
    else:
        if len(legacy) > 0:
            print("NOTE: Some openings exist on heatsink back face, but not exactly 3; leaving them unchanged.")
        else:
            print("NOTE: No legacy openings detected on heatsink back face (wire-based).")

    hs_base_solid = hs_base.val() if hasattr(hs_base, 'val') else hs_base

    # --- compute safe 4-hole layout on heatsink, preferably matching aqua offsets ---
    # Start from aqua-derived edge offsets if available; else defaults.
    if aqua_pattern:
        off_left = max(4.0, aqua_pattern['off_left'])
        off_right = max(4.0, aqua_pattern['off_right'])
        off_bottom = max(4.0, aqua_pattern['off_bottom'])
        off_top = max(4.0, aqua_pattern['off_top'])
        mount_r_guess = aqua_pattern['r_med']
    else:
        off_left = off_right = 6.0
        off_bottom = off_top = 6.0
        mount_r_guess = 1.6

    # initial positions by edge offsets
    x_low = hs_bb.xmin + off_left
    x_high = hs_bb.xmax - off_right
    z_low = hs_bb.zmin + off_bottom
    z_high = hs_bb.zmax - off_top

    # --- avoid intersection with the two large vertical bores by estimating their x centers and radii ---
    # Find cylindrical faces that look like long vertical (Z-axis) bores.
    cyl_faces = cq.Workplane(obj=hs_solid).faces('%CYLINDER').vals()
    bore_candidates = []
    for f in cyl_faces:
        bb = f.BoundingBox()
        # likely vertical if zlen large and xlen~ylen (circular section in XY)
        if bb.zlen > 0.6 * hs_bb.zlen and abs(bb.xlen - bb.ylen) < 0.8 and (min(bb.xlen, bb.ylen) > 4.0):
            r = 0.5 * min(bb.xlen, bb.ylen)
            cx = 0.5 * (bb.xmin + bb.xmax)
            cy = 0.5 * (bb.ymin + bb.ymax)
            bore_candidates.append((r, cx, cy, bb))

    bore_candidates.sort(reverse=True, key=lambda t: t[0])
    big_bores = bore_candidates[:2]

    def keepout_adjust(xa, xb, z1, z2, big_bores, r_mount, margin=1.0):
        # adjust x positions to satisfy |x - x_bore| > r_bore + r_mount + margin
        if len(big_bores) < 2:
            return xa, xb
        # compute feasible band between bores
        bores = sorted([(cx, r) for (r, cx, cy, bb) in big_bores], key=lambda t: t[0])
        (c1, r1), (c2, r2) = bores
        # Available x range on heatsink
        xmin, xmax = hs_bb.xmin, hs_bb.xmax
        # Keepout from each bore
        k1 = r1 + r_mount + margin
        k2 = r2 + r_mount + margin
        # To avoid both bores, x must satisfy x >= c1 + k1 and x <= c2 - k2
        lo = max(xmin + 2.0, c1 + k1)
        hi = min(xmax - 2.0, c2 - k2)
        if lo >= hi:
            # cannot guarantee keepout, just return original
            print(f"WARNING: No feasible x-band between big bores after keepout. lo={lo:.3f} hi={hi:.3f}")
            return xa, xb
        mid = 0.5 * (lo + hi)
        span = 0.5 * (hi - lo)
        # two columns within band
        dx = min(span * 0.85, 4.0)
        xa2 = mid - dx
        xb2 = mid + dx
        return xa2, xb2

    # apply keepout adjustment if needed
    if big_bores:
        print("Detected big vertical bores (for keepout):")
        for r, cx, cy, bb in big_bores:
            print(f"  bore: r~{r:.3f} centerX~{cx:.3f} centerY~{cy:.3f}")

    r_mount_est = max(1.4, min(2.2, mount_r_guess))
    x_low_adj, x_high_adj = keepout_adjust(x_low, x_high, z_low, z_high, big_bores, r_mount=r_mount_est, margin=1.0)

    # Ensure ordering and within bbox
    x_low, x_high = sorted([x_low_adj, x_high_adj])
    z_low, z_high = sorted([z_low, z_high])

    # Clamp z offsets to reasonable band
    z_low = max(hs_bb.zmin + 4.0, min(z_low, hs_bb.zmax - 10.0))
    z_high = min(hs_bb.zmax - 4.0, max(z_high, hs_bb.zmin + 10.0))

    print("Final heatsink 4-hole pattern (global):")
    print(f"  x_low={x_low:.3f}, x_high={x_high:.3f}, z_low={z_low:.3f}, z_high={z_high:.3f}")

    # Hole sizing: match aqua-ish radius if available
    clear_d = max(3.0, min(4.5, 2.0 * r_mount_est + 0.2))
    cbore_d = max(5.5, min(9.0, clear_d * 2.0))
    cbore_depth = 3.0
    print(f"Hole sizes: clear_d={clear_d:.3f} cbore_d={cbore_d:.3f} cbore_depth={cbore_depth:.3f}")

    # --- cut new 4-point counterbored through holes on heatsink back face ---
    hs2_wp = cq.Workplane(obj=hs_base_solid)
    mount_wp = hs2_wp.faces('<Y').workplane(centerOption='CenterOfBoundBox')
    plane2 = mount_wp.plane

    centers_global = [
        cq.Vector(x_low, y_back, z_low),
        cq.Vector(x_high, y_back, z_low),
        cq.Vector(x_low, y_back, z_high),
        cq.Vector(x_high, y_back, z_high),
    ]

    pts2d = []
    for p in centers_global:
        lp = plane2.toLocalCoords(p)
        pts2d.append((lp.x, lp.y))

    hs_modified_wp = mount_wp.pushPoints(pts2d).cboreHole(clear_d, cbore_d, cbore_depth, depth=thickness_y + 2.0)
    hs_modified_solid = hs_modified_wp.val() if hasattr(hs_modified_wp, 'val') else hs_modified_wp

    # --- rebuild compound with modified heatsink swapped in ---
    new_solids = []
    for i, s in enumerate(solids):
        if i == hs_idx:
            new_solids.append(hs_modified_solid)
        else:
            new_solids.append(s)

    result = cq.Compound.makeCompound(new_solids)
    print("Finished mounting update (iteration 2 candidate).")
    return result
