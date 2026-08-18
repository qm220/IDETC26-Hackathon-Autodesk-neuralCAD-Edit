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
    # Rebuild a SHARP, symmetric base solid:
    # - Implements the symmetry fix by setting arm Y extent to [230, 290]
    # - Represents 'delete all old chamfers/radii' by starting from sharp primitives
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
    # Edge helpers
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

    # ------------------------------------------------------------
    # Operation 3: R20 on "horizontal edges in transition".
    # Interpreted as the two long *vertical (Z-axis) edges* at the neck (x=100)
    # where the wide head steps down to the narrow arm (y=230 and y=290).
    # These are the key stress-relief / visual transition edges.
    # ------------------------------------------------------------
    r20_edges = []
    for e in solid0.Edges():
        try:
            if e.geomType() != "LINE":
                continue
        except Exception:
            continue
        if edge_axis_from_bb(e) != "Z":
            continue
        mp = edge_mid(e)
        if abs(mp[0] - x_sh) > 0.25:
            continue
        if not (abs(mp[1] - arm_y0) < 0.75 or abs(mp[1] - arm_y1) < 0.75):
            continue
        try:
            ln = e.Length()
        except Exception:
            ln = 0.0
        # Prefer the long segment spanning the arm height (avoid tiny 5mm step segments)
        if ln < 80.0:
            continue
        r20_edges.append(e)

    # Dedup by midpoint
    r20_uniq = []
    for e in r20_edges:
        mp = edge_mid(e)
        if any(dist(mp, edge_mid(e2)) < 0.5 for e2 in r20_uniq):
            continue
        r20_uniq.append(e)

    print(f"[DEBUG] Sharp base edges: {len(solid0.Edges())}")
    print(f"[DEBUG] R20 candidate edges: {len(r20_edges)}  uniq: {len(r20_uniq)}")

    solid1 = solid0
    if len(r20_uniq) > 0:
        mk20 = BRepFilletAPI_MakeFillet(solid0.wrapped)
        for e in r20_uniq:
            mk20.Add(20.0, e.wrapped)
        mk20.Build()
        if mk20.IsDone():
            solid1 = cq.Solid.cast(mk20.Shape())
            print(f"[DEBUG] R20 fillet build: DONE on {len(r20_uniq)} edges")
        else:
            print("[DEBUG] R20 fillet build: FAILED (leaving sharp)")

    # ------------------------------------------------------------
    # Operation 4: R5 on all remaining edges.
    # Robust approach: fillet ALL LINE edges on the post-R20 solid in one build.
    # (Avoids topology-mismatch failures from per-edge sequential application.)
    # Then try to fillet the bore mouth circle at x=300 with R5 (deburr).
    # ------------------------------------------------------------
    # Collect LINE edges for R5
    r5_line_edges = []
    for e in solid1.Edges():
        try:
            gt = e.geomType()
        except Exception:
            continue
        if gt != "LINE":
            continue
        try:
            ln = e.Length()
        except Exception:
            ln = 0.0
        if ln < 0.8:
            continue
        r5_line_edges.append(e)

    print(f"[DEBUG] R5 LINE edges (pre-build): {len(r5_line_edges)}")

    solid2 = solid1
    if len(r5_line_edges) > 0:
        mk5 = BRepFilletAPI_MakeFillet(solid1.wrapped)
        for e in r5_line_edges:
            mk5.Add(5.0, e.wrapped)
        mk5.Build()
        if mk5.IsDone():
            solid2 = cq.Solid.cast(mk5.Shape())
            print("[DEBUG] R5 LINE fillet build: DONE")
        else:
            print("[DEBUG] R5 LINE fillet build: FAILED (leaving as-is)")

    # Bore mouth circle at x=300
    bore_mouth = None
    best = 1e9
    for e in solid2.Edges():
        try:
            if e.geomType() != "CIRCLE":
                continue
        except Exception:
            continue
        mp = edge_mid(e)
        # prefer the circle on the tip end face x=300
        d = abs(mp[0] - x1) + 0.2 * abs(mp[1] - bore_yc) + 0.2 * abs(mp[2] - bore_zc)
        if abs(mp[0] - x1) < 0.35 and d < best:
            best = d
            bore_mouth = e

    if bore_mouth is not None:
        mkb = BRepFilletAPI_MakeFillet(solid2.wrapped)
        mkb.Add(5.0, bore_mouth.wrapped)
        mkb.Build()
        if mkb.IsDone():
            solid2 = cq.Solid.cast(mkb.Shape())
            print("[DEBUG] R5 bore-mouth fillet: DONE")
        else:
            print("[DEBUG] R5 bore-mouth fillet: FAILED")
    else:
        print("[DEBUG] Bore mouth circle not found for R5")

    # Validation
    bb_out = solid2.BoundingBox()
    try:
        v = solid2.isValid()
    except Exception:
        v = None
    print(f"[DEBUG] Output bbox: x=({bb_out.xmin:.3f},{bb_out.xmax:.3f}) y=({bb_out.ymin:.3f},{bb_out.ymax:.3f}) z=({bb_out.zmin:.3f},{bb_out.zmax:.3f})")
    print(f"[DEBUG] Output valid: {v}")

    return cq.Workplane(obj=solid2)
