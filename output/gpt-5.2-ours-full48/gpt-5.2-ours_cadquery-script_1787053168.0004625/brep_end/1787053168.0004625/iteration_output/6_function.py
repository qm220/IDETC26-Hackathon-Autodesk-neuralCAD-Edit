def my_cad_function(args):
    import cadquery as cq
    import os, math
    from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet

    # ------------------------------------------------------------
    # Load original STEP for debug/inspection only
    # ------------------------------------------------------------
    if "input_file" in args and args["input_file"]:
        p = os.path.expanduser(args["input_file"])
        if os.path.exists(p):
            src = cq.importers.importStep(p)
            sh = src.val() if hasattr(src, "val") else src
            bb = sh.BoundingBox()
            c = bb.center
            print("[DEBUG] Loaded STEP:", p)
            try:
                print(f"[DEBUG] STEP valid: {sh.isValid()}")
            except Exception:
                pass
            print(f"[DEBUG] STEP faces: {len(sh.Faces())}  edges: {len(sh.Edges())}")
            print(f"[DEBUG] STEP bbox: x=({bb.xmin:.3f},{bb.xmax:.3f}) y=({bb.ymin:.3f},{bb.ymax:.3f}) z=({bb.zmin:.3f},{bb.zmax:.3f})")
            print(f"[DEBUG] STEP center: ({c.x:.3f},{c.y:.3f},{c.z:.3f})")
        else:
            print("[DEBUG] STEP path not found:", p)

    # ------------------------------------------------------------
    # Rebuild a sharp, symmetric base solid (represents: delete all old chamfers/radii)
    # and applies the symmetry fix by making arm width symmetric about y=260.
    # ------------------------------------------------------------
    x0, x_sh, x1 = 0.0, 100.0, 300.0

    # Head (bigger section) - already symmetric about y=260
    head_y0, head_y1 = 200.0, 320.0
    head_z0, head_z1 = -450.0, -340.0

    # Arm (narrow section) - enforce symmetry about y=260 => [230, 290]
    # This implements the "move protruding side surface" operation.
    arm_y0, arm_y1 = 230.0, 290.0
    arm_z0, arm_z1 = -445.0, -340.0

    head = (
        cq.Workplane("XY")
        .box(x_sh - x0, head_y1 - head_y0, head_z1 - head_z0, centered=True)
        .translate(((x0 + x_sh) / 2.0, (head_y0 + head_y1) / 2.0, (head_z0 + head_z1) / 2.0))
    )

    arm = (
        cq.Workplane("XY")
        .box(x1 - x_sh, arm_y1 - arm_y0, arm_z1 - arm_z0, centered=True)
        .translate(((x_sh + x1) / 2.0, (arm_y0 + arm_y1) / 2.0, (arm_z0 + arm_z1) / 2.0))
    )

    base = head.union(arm)

    # ------------------------------------------------------------
    # Recreate functional features (bore + bottom pocket)
    # ------------------------------------------------------------
    # Axial blind bore along X: x=100..300
    bore_r = 14.142
    bore_yc = 260.0
    bore_zc = (arm_z0 + arm_z1) / 2.0
    bore_plane = cq.Plane(origin=(x_sh, 0, 0), xDir=(0, 1, 0), normal=(1, 0, 0))
    bore = (
        cq.Workplane(bore_plane)
        .center(bore_yc, bore_zc)
        .circle(bore_r)
        .extrude(x1 - x_sh)
    )
    base = base.cut(bore)

    # Bottom pocket
    px0, px1 = 125.350920, 168.336333
    py0, py1 = 230.0, 280.0
    pz0, pz1 = -405.071245, -374.121747
    pocket = (
        cq.Workplane("XY")
        .box(px1 - px0, py1 - py0, pz1 - pz0, centered=True)
        .translate(((px0 + px1) / 2.0, (py0 + py1) / 2.0, (pz0 + pz1) / 2.0))
    )
    base = base.cut(pocket)

    solid0 = base.val()

    # ------------------------------------------------------------
    # Helpers for robust edge identification across topology changes
    # ------------------------------------------------------------
    def bb_center(b):
        return (0.5 * (b.xmin + b.xmax), 0.5 * (b.ymin + b.ymax), 0.5 * (b.zmin + b.zmax))

    def edge_mid(e):
        try:
            p = e.positionAt(0.5)
            return (p.x, p.y, p.z)
        except Exception:
            return bb_center(e.BoundingBox())

    def edge_axis_from_bb(e):
        b = e.BoundingBox()
        dx, dy, dz = (b.xmax - b.xmin), (b.ymax - b.ymin), (b.zmax - b.zmin)
        if dx >= dy and dx >= dz:
            return "X"
        if dy >= dx and dy >= dz:
            return "Y"
        return "Z"

    def dist(a, b):
        return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2)

    # target tuple: (geomType, axis_or_None, midpoint_xyz, length_or_None)
    def find_edge_on_solid(s, target, tol=4.0):
        t_type, t_axis, t_mp, t_len = target
        best = None
        best_d = 1e9
        for e in s.Edges():
            try:
                gt = e.geomType()
            except Exception:
                continue
            if gt != t_type:
                continue
            if t_axis is not None and gt == "LINE":
                if edge_axis_from_bb(e) != t_axis:
                    continue
            mp = edge_mid(e)
            d = dist(mp, t_mp)
            if d > tol:
                continue
            if t_len is not None:
                try:
                    ln = e.Length()
                    if ln > 1e-6 and abs(ln - t_len) / max(ln, t_len) > 0.60:
                        continue
                except Exception:
                    pass
            if d < best_d:
                best_d = d
                best = e
        return best

    def fillet_one(s, radius, target, tol=4.0):
        e = find_edge_on_solid(s, target, tol=tol)
        if e is None:
            return s, False
        mk = BRepFilletAPI_MakeFillet(s.wrapped)
        try:
            mk.Add(radius, e.wrapped)
            mk.Build()
            if not mk.IsDone():
                return s, False
            return cq.Solid.cast(mk.Shape()), True
        except Exception:
            return s, False

    # ------------------------------------------------------------
    # Collect candidate edges for R20 (horizontal shoulder edges at x=100)
    # We'll detect LINE edges parallel to Y at x≈100 and z≈top/bottom levels.
    # ------------------------------------------------------------
    def mk_target(e):
        try:
            gt = e.geomType()
        except Exception:
            return None
        ax = edge_axis_from_bb(e) if gt == "LINE" else None
        mp = edge_mid(e)
        try:
            ln = e.Length()
        except Exception:
            ln = None
        return (gt, ax, mp, ln)

    r20_targets = []
    for e in solid0.Edges():
        try:
            if e.geomType() != "LINE":
                continue
        except Exception:
            continue
        ax = edge_axis_from_bb(e)
        if ax != "Y":
            continue
        mp = edge_mid(e)
        if abs(mp[0] - x_sh) > 0.5:
            continue
        # "horizontal" edges at the transition: on top plane and bottom planes near the shoulder
        if (abs(mp[2] - arm_z1) < 0.6) or (abs(mp[2] - arm_z0) < 0.6) or (abs(mp[2] - head_z0) < 0.6):
            t = mk_target(e)
            if t is not None:
                r20_targets.append(t)

    # Deduplicate R20 targets by midpoint
    r20_uniq = []
    seen = set()
    for gt, ax, mp, ln in r20_targets:
        key = (gt, ax, round(mp[0], 2), round(mp[1], 2), round(mp[2], 2))
        if key in seen:
            continue
        seen.add(key)
        r20_uniq.append((gt, ax, mp, ln))

    # Prefer longer edges first
    r20_uniq.sort(key=lambda t: (t[3] if t[3] is not None else 0.0), reverse=True)

    # ------------------------------------------------------------
    # Collect R5 targets from the sharp solid0 (LINE + CIRCLE), excluding the R20 targets.
    # Includes pocket edges; includes bore mouth edge at x=300; excludes blind-end bore edge at x=100.
    # ------------------------------------------------------------
    def is_same_target(t1, t2, mp_tol=1.0):
        # compare by type and midpoint proximity
        if t1[0] != t2[0]:
            return False
        return dist(t1[2], t2[2]) <= mp_tol

    r5_candidates = []
    for e in solid0.Edges():
        t = mk_target(e)
        if t is None:
            continue
        gt, ax, mp, ln = t
        if gt not in ("LINE", "CIRCLE"):
            continue

        # Exclude blind-end internal bore edge (circle at x=100 near bore center)
        if gt == "CIRCLE":
            if abs(mp[0] - x_sh) < 0.3 and abs(mp[1] - bore_yc) < 2.0 and abs(mp[2] - bore_zc) < 2.0:
                continue

        # Exclude R20-designated edges
        skip = False
        for rt in r20_uniq:
            if is_same_target(t, rt, mp_tol=1.5):
                skip = True
                break
        if skip:
            continue

        # Ignore extremely tiny edges
        if ln is not None and ln < 0.6:
            continue

        r5_candidates.append(t)

    # Deduplicate R5
    r5_uniq = []
    seen = set()
    for gt, ax, mp, ln in r5_candidates:
        key = (gt, ax if gt == "LINE" else None, round(mp[0], 2), round(mp[1], 2), round(mp[2], 2))
        if key in seen:
            continue
        seen.add(key)
        r5_uniq.append((gt, ax if gt == "LINE" else None, mp, ln))

    # Longer first tends to be more stable
    r5_uniq.sort(key=lambda t: (t[3] if t[3] is not None else 0.0), reverse=True)

    print(f"[DEBUG] Sharp base edges: {len(solid0.Edges())}")
    print(f"[DEBUG] R20 targets (uniq): {len(r20_uniq)}")
    print(f"[DEBUG] R5 targets (uniq): {len(r5_uniq)}")

    # ------------------------------------------------------------
    # Operation 3: Apply R20 fillets on shoulder horizontal edges
    # ------------------------------------------------------------
    solid = solid0
    r20_ok = 0
    for t in r20_uniq:
        solid_before = solid
        solid, ok = fillet_one(solid, 20.0, t, tol=4.0)
        if ok:
            r20_ok += 1
        else:
            solid = solid_before
    print(f"[DEBUG] R20 applied: {r20_ok}/{len(r20_uniq)}")

    # ------------------------------------------------------------
    # Operation 4: Apply R5 to remaining edges (best-effort), based on sharp-edge targets
    # ------------------------------------------------------------
    r5_ok = 0
    r5_fail = 0
    for t in r5_uniq:
        solid_before = solid
        solid, ok = fillet_one(solid, 5.0, t, tol=5.0)
        if ok:
            r5_ok += 1
        else:
            r5_fail += 1
            solid = solid_before
    print(f"[DEBUG] R5 applied: {r5_ok}  failed: {r5_fail}  (total targets {len(r5_uniq)})")

    # Validation
    bb_out = solid.BoundingBox()
    try:
        v = solid.isValid()
    except Exception:
        v = None
    print(f"[DEBUG] Output bbox: x=({bb_out.xmin:.3f},{bb_out.xmax:.3f}) y=({bb_out.ymin:.3f},{bb_out.ymax:.3f}) z=({bb_out.zmin:.3f},{bb_out.zmax:.3f})")
    print(f"[DEBUG] Output valid: {v}")

    return cq.Workplane(obj=solid)
