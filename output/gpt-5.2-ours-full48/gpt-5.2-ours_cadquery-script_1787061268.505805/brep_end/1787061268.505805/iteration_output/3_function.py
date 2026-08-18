def my_cad_function(args):
    import cadquery as cq
    import os, math

    input_file = os.path.expanduser(args.get("input_file", ""))
    asm_wp = cq.importers.importStep(input_file)
    root = asm_wp.val() if hasattr(asm_wp, "val") else asm_wp
    wp_root = cq.Workplane(obj=root)
    solids = wp_root.solids().vals()

    print(f"Loaded STEP: {input_file}")
    print(f"Total solids found: {len(solids)}")
    if not solids:
        print("ERROR: no solids")
        return asm_wp

    def bb_tuple(bb):
        return (bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax)

    # ---- identify heatsink (S2) ----
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
        print("WARNING: heatsink not confidently identified; returning original")
        return asm_wp

    hs_bb = hs_solid.BoundingBox()
    print(f"Selected heatsink solid index: {hs_idx} (score={hs_score:.2f})")
    print(f"Heatsink bbox: {bb_tuple(hs_bb)}")

    # ---- identify aqua/manifold (S1) candidate ----
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
        print("WARNING: could not confidently identify aqua/manifold candidate")

    # ---- utilities: robustly find circular openings on the outer Y faces ----
    def wire_circle_data(w):
        # Returns (centerVec, radius) if the wire is essentially circular
        edges = list(w.Edges())
        circ = [e for e in edges if hasattr(e, "geomType") and e.geomType() == "CIRCLE"]
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
        if (rmax - rmin) > 0.35:
            return None
        cx = sum(v.x for v in centers) / len(centers)
        cy = sum(v.y for v in centers) / len(centers)
        cz = sum(v.z for v in centers) / len(centers)
        rmean = sum(radii) / len(radii)
        return (cq.Vector(cx, cy, cz), rmean)

    def dedupe_centers(cr, tol=0.65):
        out = []
        for c, r in cr:
            keep = True
            for c2, r2 in out:
                if (c - c2).Length < tol and abs(r - r2) < 0.6:
                    keep = False
                    break
            if keep:
                out.append((c, r))
        return out

    def face_openings_on_y_extreme(solid, face_sel, yplane, ytol=0.35, rmin=0.6, rmax=8.0):
        # Collect circular wires on all planar faces at this Y extreme (handles split faces after cbore)
        faces = cq.Workplane(obj=solid).faces(face_sel).vals()
        circles = []
        for f in faces:
            try:
                if f.geomType() != "PLANE":
                    continue
            except Exception:
                # if geomType not available, still try
                pass
            try:
                if abs(f.Center().y - yplane) > ytol:
                    continue
            except Exception:
                pass
            try:
                wires = list(f.Wires())
            except Exception:
                wires = []
            for w in wires:
                cd = wire_circle_data(w)
                if cd:
                    c, r = cd
                    if rmin <= r <= rmax:
                        circles.append((c, r))
        return dedupe_centers(circles)

    def choose_mount_face_by_holes(solid, prefer_negative_y=True):
        bb = solid.BoundingBox()
        y_min, y_max = bb.ymin, bb.ymax
        cir_min = face_openings_on_y_extreme(solid, "<Y", y_min)
        cir_max = face_openings_on_y_extreme(solid, ">Y", y_max)

        # count "mount-like" openings (exclude tiny blends)
        def mountish(cirs):
            return [(c, r) for (c, r) in cirs if r >= 1.0]

        mmin = mountish(cir_min)
        mmax = mountish(cir_max)
        print(f"Mount-face probe (robust): <Y at y={y_min:.3f} circles={len(mmin)} ; >Y at y={y_max:.3f} circles={len(mmax)}")

        # prefer a face that shows legacy 3 holes, else one that shows 4, else max count
        def pick():
            candidates = [
                ("<Y", y_min, mmin),
                (">Y", y_max, mmax),
            ]
            # prefer explicit counts
            for want in (3, 4):
                hits = [c for c in candidates if len(c[2]) == want]
                if hits:
                    if prefer_negative_y:
                        hits.sort(key=lambda t: t[1])  # smaller y first
                        return hits[0]
                    return hits[0]
            # else max count
            candidates.sort(key=lambda t: (len(t[2]), -t[1] if not prefer_negative_y else -abs(t[1])), reverse=True)
            return candidates[0]

        sel, yplane, circles = pick()
        print(f"Selected mounting face: {sel} at y~{yplane:.3f} with {len(circles)} circular openings")
        return sel, yplane, circles

    def infer_2x2_from_centers(centers, tol=0.9):
        # centers: list of cq.Vector
        if len(centers) < 4:
            return None
        xs = sorted([c.x for c in centers])
        zs = sorted([c.z for c in centers])

        def cluster_1d(vals, tol):
            if not vals:
                return []
            vals = sorted(vals)
            clusters = [[vals[0]]]
            for v in vals[1:]:
                m = sum(clusters[-1]) / len(clusters[-1])
                if abs(v - m) <= tol:
                    clusters[-1].append(v)
                else:
                    clusters.append([v])
            return [sum(c) / len(c) for c in clusters]

        xcl = cluster_1d(xs, tol)
        zcl = cluster_1d(zs, tol)
        if len(xcl) < 2 or len(zcl) < 2:
            return None
        xcl = sorted(xcl)
        zcl = sorted(zcl)
        # take extremes as the 2x2 grid
        x1, x2 = xcl[0], xcl[-1]
        z1, z2 = zcl[0], zcl[-1]
        return (x1, x2, z1, z2)

    def choose_largest_face_at_y(solid, face_sel, yplane, ytol=0.35):
        faces = cq.Workplane(obj=solid).faces(face_sel).vals()
        best = None
        bestA = -1
        for f in faces:
            try:
                if abs(f.Center().y - yplane) > ytol:
                    continue
            except Exception:
                pass
            try:
                A = f.Area()
            except Exception:
                A = 0
            if A > bestA:
                bestA = A
                best = f
        return best

    # ---- determine heatsink mounting face (the one with the 3-point system, if present) ----
    hs_face_sel, hs_face_y, hs_circles = choose_mount_face_by_holes(hs_solid, prefer_negative_y=True)

    # If already 4-point on that face, be idempotent: do nothing
    hs_mount_count = len([1 for (c, r) in hs_circles if r >= 1.0])
    if hs_mount_count == 4:
        print("Heatsink mount face already shows 4 openings -> assuming already updated; no change.")
        return root

    # ---- infer aqua mounting pattern for spacing/offsets ----
    # Defaults (in case we can't infer from aqua)
    clear_d_default = 3.2
    cbore_d_default = 6.4
    cbore_depth = 3.0

    off_left = off_right = off_bot = off_top = None
    clear_d = clear_d_default
    cbore_d = cbore_d_default

    if aq_solid is not None:
        aq_bb = aq_solid.BoundingBox()
        aq_face_sel, aq_face_y, aq_circles = choose_mount_face_by_holes(aq_solid, prefer_negative_y=True)

        # group radii by center: if concentric circles exist, use min as clearance, max as cbore
        by_center = []
        for c, r in aq_circles:
            placed = False
            for item in by_center:
                if (c - item[0]).Length < 0.7:
                    item[1].append(r)
                    placed = True
                    break
            if not placed:
                by_center.append([c, [r]])

        centers = [c for (c, rs) in by_center]
        grid = infer_2x2_from_centers(centers)
        if grid:
            x1, x2, z1, z2 = grid
            off_left = x1 - aq_bb.xmin
            off_right = aq_bb.xmax - x2
            off_bot = z1 - aq_bb.zmin
            off_top = aq_bb.zmax - z2

        # infer hole diameters
        rmins, rmaxs = [], []
        for c, rs in by_center:
            rs = sorted(rs)
            rmins.append(rs[0])
            rmaxs.append(rs[-1])
        if rmins and rmaxs:
            rmin_med = sorted(rmins)[len(rmins)//2]
            rmax_med = sorted(rmaxs)[len(rmaxs)//2]
            # if clearly counterbored
            if rmax_med > 1.15 * rmin_med:
                clear_d = max(2.6, min(4.5, 2.0 * rmin_med))
                cbore_d = max(clear_d + 1.5, min(12.0, 2.0 * rmax_med))
            else:
                # single-radius holes: treat as simple through holes; still apply a mild counterbore
                clear_d = max(2.6, min(4.5, 2.0 * rmax_med))
                cbore_d = max(clear_d * 1.8, min(12.0, clear_d * 2.2))

        print(f"Aqua inferred offsets: left={off_left} right={off_right} bot={off_bot} top={off_top}")
        print(f"Aqua inferred hole stack: clear_d={clear_d:.3f} cbore_d={cbore_d:.3f} cbore_depth={cbore_depth:.3f}")

    # ---- compute heatsink 2x2 hole positions using aqua edge-offset logic (preferred), else centered spacing ----
    # Ensure edge distance
    min_edge = max(4.0, 1.25 * clear_d)

    x_low = x_high = z_low = z_high = None
    if None not in (off_left, off_right, off_bot, off_top):
        x_low = hs_bb.xmin + off_left
        x_high = hs_bb.xmax - off_right
        z_low = hs_bb.zmin + off_bot
        z_high = hs_bb.zmax - off_top

    # Fallback: centered, modest spacing
    if None in (x_low, x_high, z_low, z_high):
        xmid = 0.5 * (hs_bb.xmin + hs_bb.xmax)
        zmid = 0.5 * (hs_bb.zmin + hs_bb.zmax)
        dx = min(18.0, hs_bb.xlen * 0.45)
        dz = min(18.0, hs_bb.zlen * 0.45)
        x_low, x_high = xmid - dx/2, xmid + dx/2
        z_low, z_high = zmid - dz/2, zmid + dz/2

    # Clamp within edges
    x_low = max(x_low, hs_bb.xmin + min_edge)
    x_high = min(x_high, hs_bb.xmax - min_edge)
    z_low = max(z_low, hs_bb.zmin + min_edge)
    z_high = min(z_high, hs_bb.zmax - min_edge)

    # Ensure ordering
    if x_low > x_high:
        x_low, x_high = hs_bb.xmin + min_edge, hs_bb.xmax - min_edge
    if z_low > z_high:
        z_low, z_high = hs_bb.zmin + min_edge, hs_bb.zmax - min_edge

    print("Heatsink target 4-hole coordinates:")
    print(f"  x: {x_low:.3f}, {x_high:.3f}  z: {z_low:.3f}, {z_high:.3f}")

    # ---- build operations on selected heatsink mount face ----
    hs_face = choose_largest_face_at_y(hs_solid, hs_face_sel, hs_face_y)
    if hs_face is None:
        print("ERROR: could not locate heatsink mount face geometry")
        return asm_wp

    # Determine extrude direction INTO the solid using face normal vs bbox center
    hs_center = cq.Vector(0.5*(hs_bb.xmin+hs_bb.xmax), 0.5*(hs_bb.ymin+hs_bb.ymax), 0.5*(hs_bb.zmin+hs_bb.zmax))
    try:
        n = hs_face.normalAt()
    except Exception:
        n = cq.Vector(0, 1, 0)
    try:
        fc = hs_face.Center()
    except Exception:
        fc = cq.Vector(hs_center.x, hs_face_y, hs_center.z)
    into = 1.0 if (hs_center - fc).dot(n) > 0 else -1.0

    # Plug legacy 3 holes if present on this face (exactly 3)
    legacy = [(c, r) for (c, r) in hs_circles if r >= 1.0]
    hs_mod = cq.Workplane(obj=hs_solid)

    if len(legacy) == 3:
        print("Legacy 3-point pattern detected on heatsink mount face -> plugging")
        plug_depth = (hs_bb.ylen + 2.0)  # safe
        wp_face = cq.Workplane(obj=hs_face)
        plugs = []
        for c, r in legacy:
            # workplane is on the face; use local 2D coords derived from global point projection
            try:
                lp = wp_face.plane.toLocalCoords(c)
                px, py = lp.x, lp.y
            except Exception:
                px, py = c.x, c.z
            plugs.append(wp_face.center(px, py).circle(r * 1.05).extrude(into * plug_depth, combine=False).val())
        plug_tool = plugs[0]
        for p in plugs[1:]:
            plug_tool = plug_tool.fuse(p)
        hs_mod = cq.Workplane(obj=hs_solid).union(plug_tool)
    else:
        print(f"NOTE: legacy opening count on heatsink mount face is {len(legacy)} (not 3); not plugging.")

    hs_after_plug = hs_mod.val() if hasattr(hs_mod, "val") else hs_mod

    # Cut new 4 holes (counterbored)
    hs_after_bb = hs_after_plug.BoundingBox()
    hs_after_face = choose_largest_face_at_y(hs_after_plug, hs_face_sel, (hs_after_bb.ymin if hs_face_sel == "<Y" else hs_after_bb.ymax))
    if hs_after_face is None:
        hs_after_face = hs_face

    # Recompute into-direction after plug
    hs_after_center = cq.Vector(0.5*(hs_after_bb.xmin+hs_after_bb.xmax), 0.5*(hs_after_bb.ymin+hs_after_bb.ymax), 0.5*(hs_after_bb.zmin+hs_after_bb.zmax))
    try:
        n2 = hs_after_face.normalAt()
    except Exception:
        n2 = n
    try:
        fc2 = hs_after_face.Center()
    except Exception:
        fc2 = cq.Vector(hs_after_center.x, (hs_after_bb.ymin if hs_face_sel == "<Y" else hs_after_bb.ymax), hs_after_center.z)
    into2 = 1.0 if (hs_after_center - fc2).dot(n2) > 0 else -1.0

    wp_mount = cq.Workplane(obj=hs_after_face)
    pts_global = [
        cq.Vector(x_low, hs_face_y, z_low),
        cq.Vector(x_high, hs_face_y, z_low),
        cq.Vector(x_low, hs_face_y, z_high),
        cq.Vector(x_high, hs_face_y, z_high),
    ]
    pts2d = []
    for p in pts_global:
        try:
            lp = wp_mount.plane.toLocalCoords(p)
            pts2d.append((lp.x, lp.y))
        except Exception:
            pts2d.append((p.x, p.z))

    # Build cutter solids explicitly (more stable than selecting faces after split)
    cut_depth = hs_after_bb.ylen + 3.0
    clear_r = clear_d / 2.0
    cbore_r = cbore_d / 2.0

    clear_tools = wp_mount.pushPoints(pts2d).circle(clear_r).extrude(into2 * cut_depth, combine=False).vals()
    cbore_tools = wp_mount.pushPoints(pts2d).circle(cbore_r).extrude(into2 * cbore_depth, combine=False).vals()

    # Fuse tools
    tool = None
    for s in (clear_tools + cbore_tools):
        tool = s if tool is None else tool.fuse(s)

    hs_final = cq.Workplane(obj=hs_after_plug).cut(tool)
    hs_final_solid = hs_final.val() if hasattr(hs_final, "val") else hs_final

    # Post-check on the same extreme face: count openings again
    hs_final_bb = hs_final_solid.BoundingBox()
    y_chk = hs_final_bb.ymin if hs_face_sel == "<Y" else hs_final_bb.ymax
    chk = face_openings_on_y_extreme(hs_final_solid, hs_face_sel, y_chk)
    chk_count = len([1 for (c, r) in chk if r >= 1.0])
    print(f"Post-check: mount-face circular openings (r>=1) on {hs_face_sel} = {chk_count}")

    # ---- rebuild assembly compound ----
    new_solids = []
    for i, s in enumerate(solids):
        new_solids.append(hs_final_solid if i == hs_idx else s)

    result = cq.Compound.makeCompound(new_solids)
    print("Finished mounting update (robust face detection, aqua-offset matching when possible).")
    return result
