def my_cad_function(args):
    import cadquery as cq
    import os, math
    from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet

    # ------------------------------------------------------------
    # Debug: load original STEP (reference only)
    # ------------------------------------------------------------
    if "input_file" in args and args["input_file"]:
        p = os.path.expanduser(args["input_file"])
        if os.path.exists(p):
            src = cq.importers.importStep(p)
            sh = src.val() if hasattr(src, "val") else src
            bb = sh.BoundingBox()
            c = bb.center
            print("[DEBUG] Loaded STEP:", p)
            print(f"[DEBUG] STEP valid: {sh.isValid()}")
            print(f"[DEBUG] STEP faces: {len(sh.Faces())}  edges: {len(sh.Edges())}")
            print(f"[DEBUG] STEP bbox: x=({bb.xmin:.3f},{bb.xmax:.3f}) y=({bb.ymin:.3f},{bb.ymax:.3f}) z=({bb.zmin:.3f},{bb.zmax:.3f})")
            print(f"[DEBUG] STEP center: ({c.x:.3f},{c.y:.3f},{c.z:.3f})")

    # ------------------------------------------------------------
    # Rebuild sharp, symmetric base (removes all old chamfers/fillets)
    # ------------------------------------------------------------
    x0, x_sh, x1 = 0.0, 100.0, 300.0

    # Head block (bigger section)
    head_y0, head_y1 = 200.0, 320.0
    head_z0, head_z1 = -450.0, -340.0

    # Arm block (narrow section) -> enforce symmetry about y=260 => [230,290]
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

    result = head.union(arm)

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
    result = result.cut(bore)

    # Bottom pocket
    px0, px1 = 125.350920, 168.336333
    py0, py1 = 230.0, 280.0
    pz0, pz1 = -405.071245, -374.121747
    pocket = (
        cq.Workplane("XY")
        .box(px1 - px0, py1 - py0, pz1 - pz0, centered=True)
        .translate(((px0 + px1) / 2.0, (py0 + py1) / 2.0, (pz0 + pz1) / 2.0))
    )
    result = result.cut(pocket)

    solid = result.val()

    # ------------------------------------------------------------
    # Helpers
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

    # Find best matching edge on a given solid by geomType + axis + near midpoint (+ optional length)
    def find_edge_on_solid(s, target):
        t_type, t_axis, t_mp, t_len = target
        best = None
        best_d = 1e9
        for e in s.Edges():
            try:
                if e.geomType() != t_type:
                    continue
            except Exception:
                continue
            if edge_axis_from_bb(e) != t_axis:
                continue
            mp = edge_mid(e)
            d = dist(mp, t_mp)
            if d > 3.0:
                continue
            if t_len is not None:
                try:
                    ln = e.Length()
                    if ln > 1e-6 and abs(ln - t_len) / max(ln, t_len) > 0.50:
                        continue
                except Exception:
                    pass
            if d < best_d:
                best_d = d
                best = e
        return best

    # Single-edge fillet attempt that re-selects the edge on current topology
    def fillet_one(s, radius, target):
        e = find_edge_on_solid(s, target)
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
    # Operation 3: Apply R20 to the *two* shoulder horizontal edges of the arm section
    # (x=100, y-span=60, at z=-340 and z=-445)
    # This avoids also grabbing the head-only shoulder edges which was causing failures.
    # ------------------------------------------------------------
    targets_r20 = []
    # top shoulder edge
    targets_r20.append(("LINE", "Y", (x_sh, 260.0, arm_z1), 60.0))
    # bottom shoulder edge (arm bottom)
    targets_r20.append(("LINE", "Y", (x_sh, 260.0, arm_z0), 60.0))

    r20_success = 0
    for t in targets_r20:
        solid, ok = fillet_one(solid, 20.0, t)
        r20_success += (1 if ok else 0)
    print(f"[DEBUG] R20 applied edges: {r20_success}/2")

    # ------------------------------------------------------------
    # Operation 4: Apply R5 to all remaining edges (best-effort) excluding already-rounded ones.
    # Strategy:
    #   - Build target list from current solid using only LINE edges (external + pocket).
    #   - Incrementally fillet, re-finding each target on the evolving topology.
    # Notes:
    #   - We intentionally skip most CIRCLE edges to avoid altering bore functional edges.
    # ------------------------------------------------------------
    line_targets = []
    for e in solid.Edges():
        try:
            gt = e.geomType()
        except Exception:
            continue
        if gt != "LINE":
            continue
        try:
            ln = e.Length()
            if ln is not None and ln < 0.8:
                continue
        except Exception:
            ln = None
        ax = edge_axis_from_bb(e)
        mp = edge_mid(e)

        # Do not attempt to re-fillet edges very near the shoulder-top/bottom that should be R20
        # (after R20, these are no longer LINE, so this is mostly defensive)
        if abs(mp[0] - x_sh) < 0.8 and abs(mp[1] - 260.0) < 40.0 and (abs(mp[2] - arm_z1) < 1.0 or abs(mp[2] - arm_z0) < 1.0):
            continue

        line_targets.append(("LINE", ax, mp, ln))

    # Deduplicate targets by rounded midpoint/axis
    uniq = []
    seen = set()
    for t in line_targets:
        _, ax, mp, _ln = t
        key = (ax, round(mp[0], 2), round(mp[1], 2), round(mp[2], 2))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(t)

    print(f"[DEBUG] R5 LINE targets (dedup): {len(uniq)}")

    r5_succ = 0
    r5_fail = 0

    # Two passes: first strict matching, second relaxed (slightly larger search) by rebuilding targets
    for t in uniq:
        solid_before = solid
        solid, ok = fillet_one(solid, 5.0, t)
        if ok:
            r5_succ += 1
        else:
            r5_fail += 1
            solid = solid_before

    print(f"[DEBUG] R5 incremental pass1: success={r5_succ} fail={r5_fail}")

    # Final validation
    bb2 = solid.BoundingBox()
    try:
        valid = solid.isValid()
    except Exception:
        valid = None
    print(f"[DEBUG] Output bbox: x=({bb2.xmin:.3f},{bb2.xmax:.3f}) y=({bb2.ymin:.3f},{bb2.ymax:.3f}) z=({bb2.zmin:.3f},{bb2.zmax:.3f})")
    print(f"[DEBUG] Output valid: {valid}")

    return cq.Workplane(obj=solid)
