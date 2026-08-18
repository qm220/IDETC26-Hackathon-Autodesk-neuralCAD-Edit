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
    # Rebuild SHARP, symmetric base solid
    # - Symmetry fix: arm Y extent -> [230, 290] about y=260
    # - Remove all old chamfers/radii by starting from sharp primitives
    # ------------------------------------------------------------
    x0, x_sh, x1 = 0.0, 100.0, 300.0

    # Head (bigger section)
    head_y0, head_y1 = 200.0, 320.0
    head_z0, head_z1 = -450.0, -340.0

    # Arm (narrow section) symmetric about y=260 => [230, 290]
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
    bore_zc = (arm_z0 + arm_z1) / 2.0  # -392.5
    bore_plane = cq.Plane(origin=(x_sh, 0, 0), xDir=(0, 1, 0), normal=(1, 0, 0))
    bore = (
        cq.Workplane(bore_plane)
        .center(bore_yc, bore_zc)
        .circle(bore_r)
        .extrude(x1 - x_sh)
    )
    base = base.cut(bore)

    # Bottom pocket (dimensions from planning stage)
    px0, px1 = 125.350920, 168.336333
    py0, py1 = 230.0, 280.0
    pz0, pz1 = -405.071245, -374.121747
    pocket = (
        cq.Workplane("XY")
        .box(px1 - px0, py1 - py0, pz1 - pz0, centered=True)
        .translate(((px0 + px1) / 2.0, (py0 + py1) / 2.0, (pz0 + pz1) / 2.0))
    )
    base = base.cut(pocket)

    solid_sharp = base.val()

    # ------------------------------------------------------------
    # Edge utilities
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
        return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)

    def geom_type(e):
        try:
            return e.geomType()
        except Exception:
            return None

    def edge_sig(e):
        gt = geom_type(e)
        mp = edge_mid(e)
        ax = edge_axis_from_bb(e)
        try:
            ln = float(e.Length())
        except Exception:
            ln = 0.0
        return (gt, mp, ax, ln)

    def find_edge_by_sig(solid, sig, tol=6.0):
        gt, mp, ax, ln = sig
        best = None
        best_d = 1e9
        for e in solid.Edges():
            if geom_type(e) != gt:
                continue
            # Keep axis constraint for lines (helps avoid mismatches)
            if gt == "LINE" and edge_axis_from_bb(e) != ax:
                continue
            d = dist(edge_mid(e), mp)
            if d < best_d:
                best_d = d
                best = e
        if best is None or best_d > tol:
            return None
        return best

    def fillet_single_edge(solid, radius, sig, tol=6.0):
        e = find_edge_by_sig(solid, sig, tol=tol)
        if e is None:
            return None
        mk = BRepFilletAPI_MakeFillet(solid.wrapped)
        mk.Add(radius, e.wrapped)
        mk.Build()
        if not mk.IsDone():
            return None
        out = cq.Solid.cast(mk.Shape())
        try:
            if not out.isValid():
                return None
        except Exception:
            pass
        return out

    # ------------------------------------------------------------
    # Operation 3: Apply R20 on horizontal transition edges
    # Fix: prior attempt incorrectly targeted z=-450 (fails due to 5mm ledge).
    # Here we target z=-340 (top) and z=-445 (arm bottom) at x=100.
    # ------------------------------------------------------------
    r20_sigs = []
    for e in solid_sharp.Edges():
        if geom_type(e) != "LINE":
            continue
        if edge_axis_from_bb(e) != "Y":
            continue
        mp = edge_mid(e)
        if abs(mp[0] - x_sh) > 0.25:
            continue
        # Horizontal edges = constant Z
        b = e.BoundingBox()
        if (b.zmax - b.zmin) > 0.25:
            continue
        # Target top and arm-bottom at transition
        if not (abs(mp[2] - head_z1) < 0.25 or abs(mp[2] - arm_z0) < 0.25):
            continue
        try:
            ln = e.Length()
        except Exception:
            ln = 0.0
        if ln < 10.0:
            continue
        r20_sigs.append(edge_sig(e))

    # Dedup by midpoint proximity
    dedup = []
    for s in r20_sigs:
        _, mp, _, _ = s
        if any(dist(mp, s2[1]) < 0.5 for s2 in dedup):
            continue
        dedup.append(s)
    r20_sigs = dedup

    print(f"[DEBUG] Sharp base: faces={len(solid_sharp.Faces())} edges={len(solid_sharp.Edges())}")
    print(f"[DEBUG] R20 target edges (x=100, z=-340/-445, axis=Y): {len(r20_sigs)}")

    solid = solid_sharp
    r20_done = 0
    for sig in r20_sigs:
        out = fillet_single_edge(solid, 20.0, sig, tol=6.0)
        if out is not None:
            solid = out
            r20_done += 1
    print(f"[DEBUG] R20 applied: {r20_done}/{len(r20_sigs)}")

    # ------------------------------------------------------------
    # Operation 4: Apply R5 on all remaining sharp edges
    # Strategy: collect sharp (LINE + selected CIRCLE) edges from the SHARP model
    # excluding the R20 ones, then fillet them *one by one* (multiple features)
    # for robustness.
    # ------------------------------------------------------------
    # Helper: determine if a sig is in the R20 set (by midpoint near match)
    def is_r20_sig(sig):
        mp = sig[1]
        for s2 in r20_sigs:
            if sig[0] == s2[0] and sig[2] == s2[2] and dist(mp, s2[1]) < 0.6:
                return True
        return False

    r5_sigs = []
    for e in solid_sharp.Edges():
        gt = geom_type(e)
        if gt == "LINE":
            try:
                ln = e.Length()
            except Exception:
                ln = 0.0
            if ln < 0.8:
                continue
            sig = edge_sig(e)
            if is_r20_sig(sig):
                continue
            r5_sigs.append(sig)
        elif gt == "CIRCLE":
            # Include bore mouth circle at x=300
            mp = edge_mid(e)
            if abs(mp[0] - x1) < 0.6:
                r5_sigs.append(edge_sig(e))

    # Dedup
    dedup = []
    for s in r5_sigs:
        if any(s[0] == s2[0] and s[2] == s2[2] and dist(s[1], s2[1]) < 0.5 for s2 in dedup):
            continue
        dedup.append(s)
    r5_sigs = dedup

    # Apply longer edges first for stability
    r5_sigs.sort(key=lambda s: -s[3])

    print(f"[DEBUG] R5 target edges (excl R20): {len(r5_sigs)}")

    r5_done = 0
    r5_fail = 0
    for sig in r5_sigs:
        out = fillet_single_edge(solid, 5.0, sig, tol=8.0)
        if out is not None:
            solid = out
            r5_done += 1
        else:
            r5_fail += 1

    print(f"[DEBUG] R5 applied: {r5_done}/{len(r5_sigs)}  failed: {r5_fail}")

    # Validation
    bb_out = solid.BoundingBox()
    try:
        v = solid.isValid()
    except Exception:
        v = None
    print(f"[DEBUG] Output bbox: x=({bb_out.xmin:.3f},{bb_out.xmax:.3f}) y=({bb_out.ymin:.3f},{bb_out.ymax:.3f}) z=({bb_out.zmin:.3f},{bb_out.zmax:.3f})")
    print(f"[DEBUG] Output valid: {v}")

    return cq.Workplane(obj=solid)
