def my_cad_function(args):
    import cadquery as cq
    import os

    # ---- Load model ----
    input_file = os.path.expanduser(args.get("input_file", ""))
    shape_wp = cq.importers.importStep(input_file)
    shp = shape_wp.val() if hasattr(shape_wp, "val") else shape_wp

    bb = shp.BoundingBox()
    print(f"Loaded STEP: {input_file}")
    print(f"Valid (as imported): {shp.isValid()}")
    print(f"Faces: {len(shp.Faces())}, Solids: {len(shp.Solids())}")
    print(f"BBox xmin/xmax: {bb.xmin:.3f}/{bb.xmax:.3f}")
    print(f"BBox ymin/ymax: {bb.ymin:.3f}/{bb.ymax:.3f}")
    print(f"BBox zmin/zmax: {bb.zmin:.3f}/{bb.zmax:.3f}")
    print(f"BBox center: ({bb.center.x:.3f}, {bb.center.y:.3f}, {bb.center.z:.3f})")

    # ---- Find a large horizontal planar "top" face ----
    y_flat_tol = 0.5  # mm
    ref_area = max(1.0, bb.xlen * bb.zlen)
    min_area = 0.03 * ref_area

    top_candidates = []  # (y, area, face)
    for f in shp.Faces():
        try:
            if hasattr(f, "geomType") and f.geomType() == "PLANE":
                fb = f.BoundingBox()
                if (fb.ymax - fb.ymin) <= y_flat_tol and f.Area() >= min_area:
                    top_candidates.append((fb.ymax, f.Area(), f))
        except Exception:
            continue

    if not top_candidates:
        y_top = bb.ymax
        f_top = None
        top_fb = None
        print("WARNING: No suitable top planar face found; using bbox.ymax")
    else:
        y_top = max(c[0] for c in top_candidates)
        near = [c for c in top_candidates if abs(c[0] - y_top) < 2.0]
        y_top, a_top, f_top = max(near, key=lambda t: t[1])
        top_fb = f_top.BoundingBox()
        fc = f_top.Center()
        print(
            f"Top face: y={y_top:.3f}, area={a_top:.1f}, face_center=({fc.x:.3f},{fc.y:.3f},{fc.z:.3f}), face_bbox_x=({top_fb.xmin:.3f},{top_fb.xmax:.3f}), face_bbox_z=({top_fb.zmin:.3f},{top_fb.zmax:.3f})"
        )

    # ---- Try to detect an existing filler boss near the very top (BSPLINE/other non-planar) ----
    # Use bounding-box heuristics to find a compact, topmost protrusion.
    boss_guess = None  # (score, x, z, face)
    y_boss_band = 3.0
    for f in shp.Faces():
        try:
            gt = f.geomType() if hasattr(f, "geomType") else None
            if gt in ("PLANE", "CYLINDER", "CONE"):
                continue
            fb = f.BoundingBox()
            if abs(fb.ymax - bb.ymax) > y_boss_band:
                continue
            # compact-ish in XZ (boss shouldn't span the entire radiator)
            if fb.xlen < 8 or fb.zlen < 8:
                continue
            if fb.xlen > 120 or fb.zlen > 120:
                continue
            # score: prefer higher, then more compact
            score = (fb.ymax - bb.ymax) - 0.02 * (fb.xlen + fb.zlen)
            xg, zg = (fb.xmin + fb.xmax) / 2.0, (fb.zmin + fb.zmax) / 2.0
            if boss_guess is None or score > boss_guess[0]:
                boss_guess = (score, xg, zg, f)
        except Exception:
            continue

    # ---- Decide neck center ----
    # Design intent: centered between fan bays => z ~ 0. Use 0 if within top-face span, else fallback.
    if top_fb is not None and (top_fb.zmin <= 0.0 <= top_fb.zmax):
        cz = 0.0
    elif boss_guess is not None:
        cz = boss_guess[2]
    else:
        cz = bb.center.z

    # X: prefer existing boss x if detected; otherwise use a clamped mid-thickness to avoid being pulled to a side ledge.
    if boss_guess is not None:
        cx = boss_guess[1]
        print(f"Boss guess near top: x={cx:.3f}, z={boss_guess[2]:.3f}, geomType={boss_guess[3].geomType() if hasattr(boss_guess[3],'geomType') else 'n/a'}")
    else:
        cx = bb.center.x

    # Clamp (cx,cz) inside the top-face bbox (with margin) if we have it, so the neck is guaranteed to sit on the top plane.
    if top_fb is not None:
        m = 8.0
        cx = max(top_fb.xmin + m, min(top_fb.xmax - m, cx))
        cz = max(top_fb.zmin + m, min(top_fb.zmax - m, cz))

    print(f"Filler placement: y={y_top:.3f}, cx={cx:.3f}, cz={cz:.3f}")

    # ---- Parameters (mm) ----
    neck_od = 42.0
    neck_id = 32.0
    neck_h = 26.0

    # cut depth: enough to break through typical tank wall and into header volume, but not overly deep
    cut_depth_into_tank = 18.0

    seat_h = 3.0
    seat_od = 54.0

    # simple bayonet lugs (visual)
    lug_len = 14.0   # X direction
    lug_depth = 8.0  # Z direction
    lug_thk = 2.5    # Y direction

    # Cap (separate body)
    cap_od = 64.0
    cap_h = 24.0
    cap_insert_depth = 16.0
    cap_clearance = 0.8
    wing_span = 22.0   # added diameter via wings
    wing_w = 10.0

    # ---- Build workplanes (top plane is XZ, normal +Y) ----
    top_wpl = cq.Workplane("XZ", origin=(0, y_top, 0)).center(cx, cz)

    # 1) Create pouring opening into tank
    cut_tool = top_wpl.circle(neck_id / 2.0).extrude(-cut_depth_into_tank)
    modified = cq.Workplane(obj=shp).cut(cut_tool)

    # 2) Create filler neck (simple tube)
    neck = top_wpl.circle(neck_od / 2.0).circle(neck_id / 2.0).extrude(neck_h)

    # 3) Seal seat ring at top
    seat_wpl = cq.Workplane("XZ", origin=(0, y_top + neck_h - seat_h, 0)).center(cx, cz)
    seat = seat_wpl.circle(seat_od / 2.0).circle(neck_od / 2.0).extrude(seat_h)

    # 4) Bayonet lugs near neck top (2 opposite)
    lug_y = y_top + neck_h - lug_thk
    lugs_wpl = cq.Workplane("XZ", origin=(0, lug_y, 0)).center(cx, cz)
    lug_r = neck_od / 2.0 + lug_depth / 2.0
    # place lugs along +Z and -Z (simple)
    lugs = (
        lugs_wpl
        .pushPoints([(0, lug_r), (0, -lug_r)])
        .rect(lug_len, lug_depth)
        .extrude(lug_thk)
    )

    # Union filler features onto radiator
    modified = modified.union(neck).union(seat).union(lugs)

    # ---- Create cap as separate body (with simple wings + internal clearance + lug pockets) ----
    # Cap sits over neck; bottom positioned so insert overlaps neck.
    cap_y0 = y_top + neck_h - cap_insert_depth
    cap_wpl = cq.Workplane("XZ", origin=(0, cap_y0, 0)).center(cx, cz)

    # Main cap cylinder
    cap_body = cap_wpl.circle(cap_od / 2.0).extrude(cap_h)

    # Wings for grip (a cross-like profile)
    wings = (
        cap_wpl
        .rect(cap_od + wing_span, wing_w)
        .extrude(cap_h)
        .union(cap_wpl.rect(wing_w, cap_od + wing_span).extrude(cap_h))
    )
    cap_body = cap_body.union(wings)

    # Internal bore clearance
    inner_id = neck_od + 2.0 * cap_clearance
    inner_cut = cap_wpl.circle(inner_id / 2.0).extrude(cap_insert_depth + 6.0)
    cap_body = cap_body.cut(inner_cut)

    # Simple lug pockets (match lug positions so it looks like it could lock)
    pocket_wpl = cq.Workplane("XZ", origin=(0, cap_y0 + 2.0, 0)).center(cx, cz)
    pockets = (
        pocket_wpl
        .pushPoints([(0, lug_r), (0, -lug_r)])
        .rect(lug_len + 2.0, lug_depth + 1.5)
        .extrude(cap_insert_depth)
    )
    cap_body = cap_body.cut(pockets)

    # Top recess detail
    recess = (
        cq.Workplane("XZ", origin=(0, cap_y0 + cap_h - 3.0, 0))
        .center(cx, cz)
        .circle((cap_od - 10.0) / 2.0)
        .extrude(3.0)
    )
    cap_body = cap_body.cut(recess)

    # ---- Return as assembly so cap stays separate ----
    asm = cq.Assembly(name="radiator_with_filler")
    asm.add(modified, name="radiator")
    asm.add(cap_body, name="cap")

    print("Added: filler opening + neck + seat + lugs; cap with wings + internal clearance + lug pockets (separate body).")
    return asm
