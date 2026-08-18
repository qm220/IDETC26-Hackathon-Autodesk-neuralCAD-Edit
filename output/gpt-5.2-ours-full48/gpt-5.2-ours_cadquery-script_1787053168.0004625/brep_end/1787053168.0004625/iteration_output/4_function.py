def my_cad_function(args):
    import cadquery as cq
    import os, math
    from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet

    # ------------------------------------------------------------
    # Load STEP for debug (reference only)
    # ------------------------------------------------------------
    if "input_file" in args and args["input_file"] and os.path.exists(os.path.expanduser(args["input_file"])):
        src = cq.importers.importStep(os.path.expanduser(args["input_file"]))
        sh = src.val() if hasattr(src, "val") else src
        bb = sh.BoundingBox()
        c = bb.center
        print("[DEBUG] Loaded STEP:", os.path.expanduser(args["input_file"]))
        print(f"[DEBUG] STEP valid: {sh.isValid()}")
        print(f"[DEBUG] STEP faces: {len(sh.Faces())}  edges: {len(sh.Edges())}")
        print(f"[DEBUG] STEP bbox: x=({bb.xmin:.3f},{bb.xmax:.3f}) y=({bb.ymin:.3f},{bb.ymax:.3f}) z=({bb.zmin:.3f},{bb.zmax:.3f})")
        print(f"[DEBUG] STEP center: ({c.x:.3f},{c.y:.3f},{c.z:.3f})")

    # ------------------------------------------------------------
    # Rebuild sharp, symmetric base (removes all chamfers/fillets)
    # ------------------------------------------------------------
    x0, x_shoulder, x_tip = 0.0, 100.0, 300.0

    # Head (larger section)
    head_y_min, head_y_max = 200.0, 320.0
    head_z_min, head_z_max = -450.0, -340.0

    # Arm (narrow section) - enforce symmetry about y=260 => y=[230,290]
    arm_y_min, arm_y_max = 230.0, 290.0
    arm_z_min, arm_z_max = -445.0, -340.0

    head = (
        cq.Workplane("XY")
        .box(x_shoulder - x0, head_y_max - head_y_min, head_z_max - head_z_min, centered=True)
        .translate(((x0 + x_shoulder) / 2.0, (head_y_min + head_y_max) / 2.0, (head_z_min + head_z_max) / 2.0))
    )

    arm = (
        cq.Workplane("XY")
        .box(x_tip - x_shoulder, arm_y_max - arm_y_min, arm_z_max - arm_z_min, centered=True)
        .translate(((x_shoulder + x_tip) / 2.0, (arm_y_min + arm_y_max) / 2.0, (arm_z_min + arm_z_max) / 2.0))
    )

    result = head.union(arm)

    # ------------------------------------------------------------
    # Recreate functional features (bore + bottom pocket)
    # ------------------------------------------------------------
    # Axial blind bore along X: from x=100 to x=300
    bore_r = 14.142
    bore_yc = 260.0
    bore_zc = (arm_z_min + arm_z_max) / 2.0
    bore_plane = cq.Plane(origin=(x_shoulder, 0, 0), xDir=(0, 1, 0), normal=(1, 0, 0))  # YZ plane at x=100
    bore = (
        cq.Workplane(bore_plane)
        .center(bore_yc, bore_zc)
        .circle(bore_r)
        .extrude(x_tip - x_shoulder)
    )
    result = result.cut(bore)

    # Bottom pocket (planning numbers)
    px0, px1 = 125.350920, 168.336333
    py0, py1 = 230.0, 280.0
    pz0, pz1 = -405.071245, -374.121747

    pocket = (
        cq.Workplane("XY")
        .box(px1 - px0, py1 - py0, pz1 - pz0, centered=True)
        .translate(((px0 + px1) / 2.0, (py0 + py1) / 2.0, (pz0 + pz1) / 2.0))
    )
    result = result.cut(pocket)

    sharp = result.val()

    # ------------------------------------------------------------
    # Edge helpers
    # ------------------------------------------------------------
    def edge_midpoint(e):
        try:
            p = e.positionAt(0.5)
            return (p.x, p.y, p.z)
        except Exception:
            bb = e.BoundingBox()
            return (0.5 * (bb.xmin + bb.xmax), 0.5 * (bb.ymin + bb.ymax), 0.5 * (bb.zmin + bb.zmax))

    def edge_axis(e):
        bb = e.BoundingBox()
        dx = bb.xmax - bb.xmin
        dy = bb.ymax - bb.ymin
        dz = bb.zmax - bb.zmin
        if dx >= dy and dx >= dz:
            return "X"
        if dy >= dx and dy >= dz:
            return "Y"
        return "Z"

    def dist(a, b):
        return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2)

    tol_plane = 0.40
    tol_span = 0.80

    # ------------------------------------------------------------
    # R20 selection: horizontal (non-vertical) edges on shoulder plane x=100
    # interpreted as the "horizontal edges where narrow and bigger meet".
    # We target LINE edges lying on x=100, running along Y.
    # ------------------------------------------------------------
    def is_r20_edge(e):
        try:
            if e.geomType() != "LINE":
                return False
        except Exception:
            return False

        bb = e.BoundingBox()
        cx = 0.5 * (bb.xmin + bb.xmax)
        cz = 0.5 * (bb.zmin + bb.zmax)
        dx = bb.xmax - bb.xmin
        dy = bb.ymax - bb.ymin
        dz = bb.zmax - bb.zmin

        # Must lie on shoulder plane and be a Y-directed line (horizontal)
        if abs(cx - x_shoulder) > tol_plane:
            return False
        if dx > tol_span or dz > tol_span:
            return False
        if dy < 10.0:
            return False

        # Must be at the shoulder top or shoulder bottom levels
        if not (
            abs(cz - arm_z_max) <= tol_plane or
            abs(cz - arm_z_min) <= tol_plane or
            abs(cz - head_z_min) <= tol_plane
        ):
            return False

        return True

    # ------------------------------------------------------------
    # Attempt 1: Single multi-radius fillet (R20 on shoulder horizontals, R5 elsewhere)
    # Apply to ALL LINE edges so we don't miss tip/head edges.
    # ------------------------------------------------------------
    all_edges = list(sharp.Edges())
    line_edges = []
    for e in all_edges:
        try:
            if e.geomType() == "LINE":
                line_edges.append(e)
        except Exception:
            pass

    r20_edges = [e for e in line_edges if is_r20_edge(e)]
    r5_edges = [e for e in line_edges if not is_r20_edge(e)]

    print(f"[DEBUG] Sharp edges: total={len(all_edges)} line={len(line_edges)}")
    print(f"[DEBUG] R20 target LINE edges: {len(r20_edges)}")
    print(f"[DEBUG] R5 target LINE edges: {len(r5_edges)}")

    def build_multiradius(solid_in, edges20, edges5):
        mk = BRepFilletAPI_MakeFillet(solid_in.wrapped)
        added20 = 0
        added5 = 0
        for e in edges20:
            try:
                mk.Add(20.0, e.wrapped)
                added20 += 1
            except Exception:
                pass
        for e in edges5:
            try:
                mk.Add(5.0, e.wrapped)
                added5 += 1
            except Exception:
                pass
        if added20 + added5 == 0:
            return solid_in, False
        mk.Build()
        if not mk.IsDone():
            return solid_in, False
        out = cq.Solid.cast(mk.Shape())
        return out, True

    solid_out, ok = build_multiradius(sharp, r20_edges, r5_edges)
    print(f"[DEBUG] Multi-radius fillet build ok: {ok}")

    # ------------------------------------------------------------
    # Fallback: R20 first, then R5 (matched back to sharp-edge targets)
    # ------------------------------------------------------------
    if not ok:
        # R20 only
        mk20 = BRepFilletAPI_MakeFillet(sharp.wrapped)
        add20 = 0
        for e in r20_edges:
            try:
                mk20.Add(20.0, e.wrapped)
                add20 += 1
            except Exception:
                pass
        mk20.Build()
        if mk20.IsDone() and add20 > 0:
            solid20 = cq.Solid.cast(mk20.Shape())
            print(f"[DEBUG] Fallback R20 ok: True (added={add20})")
        else:
            solid20 = sharp
            print(f"[DEBUG] Fallback R20 ok: False (added={add20})")

        # Build R5 targets from sharp model (exclude r20 edges)
        r5_targets = []
        for e in r5_edges:
            mp = edge_midpoint(e)
            ax = edge_axis(e)
            try:
                ln = e.Length()
            except Exception:
                ln = None
            r5_targets.append((mp, ax, ln))

        def find_matching_line_edge(solid_now, target_mp, target_axis, target_len=None):
            best = None
            best_d = 1e9
            for e in solid_now.Edges():
                try:
                    if e.geomType() != "LINE":
                        continue
                except Exception:
                    continue
                if edge_axis(e) != target_axis:
                    continue
                mp = edge_midpoint(e)
                d = dist(mp, target_mp)
                if d > 3.5:
                    continue
                if target_len is not None:
                    try:
                        ln = e.Length()
                        if ln > 0 and abs(ln - target_len) / max(ln, target_len) > 0.40:
                            continue
                    except Exception:
                        pass
                if d < best_d:
                    best_d = d
                    best = e
            return best

        matched = []
        for (mp, ax, ln) in r5_targets:
            em = find_matching_line_edge(solid20, mp, ax, ln)
            if em is not None:
                matched.append(em)

        # Deduplicate by hash of wrapped
        uniq = []
        seen = set()
        for e in matched:
            key = (round(edge_midpoint(e)[0], 3), round(edge_midpoint(e)[1], 3), round(edge_midpoint(e)[2], 3), edge_axis(e))
            if key in seen:
                continue
            seen.add(key)
            uniq.append(e)

        print(f"[DEBUG] Fallback R5 matched edges: {len(uniq)} (from targets={len(r5_targets)})")

        mk5 = BRepFilletAPI_MakeFillet(solid20.wrapped)
        add5 = 0
        for e in uniq:
            try:
                mk5.Add(5.0, e.wrapped)
                add5 += 1
            except Exception:
                pass
        mk5.Build()
        if mk5.IsDone() and add5 > 0:
            solid_out = cq.Solid.cast(mk5.Shape())
            ok = True
            print(f"[DEBUG] Fallback R5 ok: True (added={add5})")
        else:
            # last resort: incremental single-edge R5
            solid_now = solid20
            succ = 0
            fail = 0
            for e in uniq:
                mk = BRepFilletAPI_MakeFillet(solid_now.wrapped)
                try:
                    mk.Add(5.0, e.wrapped)
                    mk.Build()
                    if not mk.IsDone():
                        fail += 1
                        continue
                    solid_now = cq.Solid.cast(mk.Shape())
                    succ += 1
                except Exception:
                    fail += 1
            solid_out = solid_now
            ok = True
            print(f"[DEBUG] Fallback R5 incremental: success={succ} fail={fail}")

    # Final debug
    bb2 = solid_out.BoundingBox()
    print(f"[DEBUG] Output bbox: x=({bb2.xmin:.3f},{bb2.xmax:.3f}) y=({bb2.ymin:.3f},{bb2.ymax:.3f}) z=({bb2.zmin:.3f},{bb2.zmax:.3f})")
    try:
        print(f"[DEBUG] Output valid: {solid_out.isValid()}")
    except Exception:
        pass

    return cq.Workplane(obj=solid_out)
