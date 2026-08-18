def my_cad_function(args):
    import cadquery as cq
    import os

    # ----------------------
    # Load model
    # ----------------------
    input_file = os.path.expanduser(args.get("input_file", ""))
    shape_wp = cq.importers.importStep(input_file)
    shp = shape_wp.val() if hasattr(shape_wp, "val") else shape_wp

    bb = shp.BoundingBox()
    print(f"Loaded STEP: {input_file}")
    try:
        print(f"Valid (as imported): {shp.isValid()}")
    except Exception:
        pass
    print(f"Faces: {len(shp.Faces())}, Solids: {len(shp.Solids())}")
    print(f"BBox xmin/xmax: {bb.xmin:.3f}/{bb.xmax:.3f}")
    print(f"BBox ymin/ymax: {bb.ymin:.3f}/{bb.ymax:.3f}")
    print(f"BBox zmin/zmax: {bb.zmin:.3f}/{bb.zmax:.3f}")
    print(f"BBox center: ({bb.center.x:.3f}, {bb.center.y:.3f}, {bb.center.z:.3f})")

    # ----------------------
    # Heuristic: find existing filler boss near top
    # We will use it as the datum for the pouring section + cap.
    # ----------------------
    top_band = 18.0  # mm below bbox.ymax to search
    boss_faces = []
    for f in shp.Faces():
        try:
            gt = f.geomType() if hasattr(f, "geomType") else None
            fb = f.BoundingBox()
            # Must be close to the top of the entire model
            if (bb.ymax - fb.ymax) > top_band:
                continue
            # Avoid huge top planes; prefer localized protrusion faces
            if fb.xlen > 120 or fb.zlen > 140:
                continue
            if fb.xlen < 6 or fb.zlen < 6:
                continue
            # Prefer non-planar (boss is often BSPLINE/cyl)
            nonplanar = (gt is None) or (gt != "PLANE")
            # area filter to reject tiny slivers
            if f.Area() < 30:
                continue
            score = 0.0
            score += 5.0 if nonplanar else 0.0
            score += (fb.ymax - (bb.ymax - top_band)) / max(1e-6, top_band)
            score -= 0.01 * (fb.xlen + fb.zlen)
            boss_faces.append((score, f, fb, gt))
        except Exception:
            continue

    boss_faces.sort(key=lambda t: t[0], reverse=True)

    if boss_faces:
        # take top N and build a combined bbox cluster around the best one
        best_score, best_face, best_fb, best_gt = boss_faces[0]
        cx0 = (best_fb.xmin + best_fb.xmax) * 0.5
        cz0 = (best_fb.zmin + best_fb.zmax) * 0.5

        # cluster faces whose centers are near (cx0, cz0)
        cluster = []
        for sc, f, fb, gt in boss_faces[:60]:
            cxi = (fb.xmin + fb.xmax) * 0.5
            czi = (fb.zmin + fb.zmax) * 0.5
            if abs(cxi - cx0) < 35 and abs(czi - cz0) < 35:
                cluster.append((sc, f, fb, gt))

        # combined bbox
        xmin = min(item[2].xmin for item in cluster)
        xmax = max(item[2].xmax for item in cluster)
        ymin = min(item[2].ymin for item in cluster)
        ymax = max(item[2].ymax for item in cluster)
        zmin = min(item[2].zmin for item in cluster)
        zmax = max(item[2].zmax for item in cluster)

        boss_bb = type("BB", (), {})()
        boss_bb.xmin, boss_bb.xmax = xmin, xmax
        boss_bb.ymin, boss_bb.ymax = ymin, ymax
        boss_bb.zmin, boss_bb.zmax = zmin, zmax
        boss_bb.xlen, boss_bb.ylen, boss_bb.zlen = (xmax - xmin), (ymax - ymin), (zmax - zmin)

        cx = (xmin + xmax) * 0.5
        cz = (zmin + zmax) * 0.5
        y_boss_top = ymax
        print(f"Boss cluster found: gt(best)={best_gt}, score={best_score:.3f}")
        print(f"Boss bbox: x[{xmin:.3f},{xmax:.3f}] y[{ymin:.3f},{ymax:.3f}] z[{zmin:.3f},{zmax:.3f}]")
        print(f"Boss center guess: cx={cx:.3f}, cz={cz:.3f}, y_top={y_boss_top:.3f}")
    else:
        boss_bb = None
        cx, cz = bb.center.x, bb.center.z
        y_boss_top = bb.ymax
        print("WARNING: No boss-like faces found near top; falling back to bbox center.")

    # ----------------------
    # Find a large horizontal planar face near the boss to use as tank top datum.
    # (This helps ensure the opening starts at the top tank surface.)
    # ----------------------
    y_flat_tol = 0.6
    min_area = 0.02 * (bb.xlen * bb.zlen)
    y_search_low = bb.ymin
    y_search_high = y_boss_top + 2.0

    top_planes = []  # (abs(y - y_target), -area, y, face)
    y_target = y_boss_top - 8.0
    for f in shp.Faces():
        try:
            if not (hasattr(f, "geomType") and f.geomType() == "PLANE"):
                continue
            fb = f.BoundingBox()
            if (fb.ymax - fb.ymin) > y_flat_tol:
                continue
            y = fb.ymax
            if not (y_search_low <= y <= y_search_high):
                continue
            a = f.Area()
            if a < min_area:
                continue
            top_planes.append((abs(y - y_target), -a, y, f, fb))
        except Exception:
            continue

    if top_planes:
        top_planes.sort(key=lambda t: (t[0], t[1]))
        _, _, y_tank_top, f_top, fb_top = top_planes[0]
        # clamp placement to inside this top plane bbox (margin)
        m = 6.0
        cx = max(fb_top.xmin + m, min(fb_top.xmax - m, cx))
        cz = max(fb_top.zmin + m, min(fb_top.zmax - m, cz))
        print(f"Top planar tank face: y={y_tank_top:.3f}, area={f_top.Area():.1f}, bbox_x=({fb_top.xmin:.3f},{fb_top.xmax:.3f}), bbox_z=({fb_top.zmin:.3f},{fb_top.zmax:.3f})")
    else:
        # fallback: assume boss starts at its ymin
        y_tank_top = boss_bb.ymin if boss_bb is not None else (bb.ymax - 12.0)
        print(f"WARNING: No suitable top planar tank face found; using y_tank_top={y_tank_top:.3f}")

    # Encourage the intent z≈0 when feasible: if 0 is inside the top face span, snap.
    if top_planes:
        if fb_top.zmin <= 0.0 <= fb_top.zmax:
            cz = 0.0
            print("Snapped filler cz to 0.0 to match mid-plane between fan bays.")

    print(f"FINAL filler placement: y_tank_top={y_tank_top:.3f}, cx={cx:.3f}, cz={cz:.3f}, y_boss_top={y_boss_top:.3f}")

    # ----------------------
    # Parameters (mm) - simplified automotive-style bayonet cap/neck
    # ----------------------
    neck_od = 42.0
    neck_id = 32.0
    collar_h = 8.0           # small collar to emphasize pouring section without overbuilding existing boss
    seat_h = 3.0
    seat_od = 54.0

    cut_extra_above = 8.0    # start cut above boss to guarantee intersection
    cut_depth = 45.0         # cut down into tank region (heuristic; avoids requiring internal cavity detection)

    lug_len = 14.0
    lug_depth = 8.0
    lug_thk = 2.5

    # Cap
    cap_od = 64.0
    cap_h = 24.0
    cap_insert_depth = 16.0
    cap_clearance = 0.8
    wing_span = 22.0
    wing_w = 10.0

    # ----------------------
    # 1) Pouring opening cut (functional opening)
    # ----------------------
    # Use a tall cut cylinder starting above the boss and extending down.
    cut_wpl = cq.Workplane("XZ", origin=(0, y_boss_top + cut_extra_above, 0)).center(cx, cz)
    cut_tool = cut_wpl.circle(neck_id / 2.0).extrude(-cut_depth)
    modified = cq.Workplane(obj=shp).cut(cut_tool)

    # ----------------------
    # 1b) Add a small collar + seat ring at/above the boss top (visual pouring section standardization)
    # ----------------------
    collar_y0 = max(y_tank_top, y_boss_top - collar_h)  # avoid putting collar below tank top
    collar_wpl = cq.Workplane("XZ", origin=(0, collar_y0, 0)).center(cx, cz)
    collar = collar_wpl.circle(neck_od / 2.0).circle(neck_id / 2.0).extrude(max(2.0, y_boss_top - collar_y0))

    seat_wpl = cq.Workplane("XZ", origin=(0, y_boss_top - seat_h, 0)).center(cx, cz)
    seat = seat_wpl.circle(seat_od / 2.0).circle(neck_od / 2.0).extrude(seat_h)

    # Bayonet lugs near boss top
    lug_y0 = y_boss_top - lug_thk
    lugs_wpl = cq.Workplane("XZ", origin=(0, lug_y0, 0)).center(cx, cz)
    lug_r = neck_od / 2.0 + lug_depth / 2.0
    lugs = (
        lugs_wpl
        .pushPoints([(0, lug_r), (0, -lug_r)])
        .rect(lug_len, lug_depth)
        .extrude(lug_thk)
    )

    modified = modified.union(collar).union(seat).union(lugs)

    # ----------------------
    # 2) Cap as separate body
    # ----------------------
    # Seat the cap relative to boss top so it visually closes the opening.
    cap_y0 = y_boss_top - cap_insert_depth + 1.0
    cap_wpl = cq.Workplane("XZ", origin=(0, cap_y0, 0)).center(cx, cz)

    cap_body = cap_wpl.circle(cap_od / 2.0).extrude(cap_h)
    wings = (
        cap_wpl
        .rect(cap_od + wing_span, wing_w)
        .extrude(cap_h)
        .union(cap_wpl.rect(wing_w, cap_od + wing_span).extrude(cap_h))
    )
    cap_body = cap_body.union(wings)

    # internal clearance
    inner_id = neck_od + 2.0 * cap_clearance
    inner_cut = cap_wpl.circle(inner_id / 2.0).extrude(cap_insert_depth + 8.0)
    cap_body = cap_body.cut(inner_cut)

    # lug pockets
    pocket_wpl = cq.Workplane("XZ", origin=(0, cap_y0 + 2.0, 0)).center(cx, cz)
    pockets = (
        pocket_wpl
        .pushPoints([(0, lug_r), (0, -lug_r)])
        .rect(lug_len + 2.0, lug_depth + 1.5)
        .extrude(cap_insert_depth)
    )
    cap_body = cap_body.cut(pockets)

    # top recess detail
    recess = (
        cq.Workplane("XZ", origin=(0, cap_y0 + cap_h - 3.0, 0))
        .center(cx, cz)
        .circle((cap_od - 10.0) / 2.0)
        .extrude(3.0)
    )
    cap_body = cap_body.cut(recess)

    # ----------------------
    # Return assembly (cap remains separate)
    # ----------------------
    asm = cq.Assembly(name="radiator_with_filler")
    asm.add(modified, name="radiator")
    asm.add(cap_body, name="cap")

    print("Added/standardized filler: cut opening + collar + seat + lugs; added cap as separate body.")
    return asm
