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
    # - Symmetry fix: arm Y extent -> [230, 290] about y=260
    # - 'Delete all chamfers/radii' -> start from sharp primitives
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

    def build_fillet(solid, radius, edges):
        mk = BRepFilletAPI_MakeFillet(solid.wrapped)
        for e in edges:
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
    # Operation 3: R20 on specified *horizontal* transition edges
    # Interpreted per planning stage: edges at x=100 where the shoulder meets
    # the TOP and BOTTOM planes (edges parallel to global Y).
    # NOTE: we intentionally avoid the small 5mm bottom ledge edge at z=-445
    # because R20 cannot fit there.
    # ------------------------------------------------------------
    r20_candidates = []
    for e in solid0.Edges():
        try:
            if e.geomType() != "LINE":
                continue
        except Exception:
            continue
        if edge_axis_from_bb(e) != "Y":
            continue
        mp = edge_mid(e)
        if abs(mp[0] - x_sh) > 0.25:
            continue
        # Only top (z=-340) and head bottom (z=-450) shoulder edges
        if not (abs(mp[2] - head_z1) < 0.25 or abs(mp[2] - head_z0) < 0.25):
            continue
        try:
            ln = e.Length()
        except Exception:
            ln = 0.0
        if ln < 15.0:
            continue
        r20_candidates.append(e)

    # Dedup by midpoint
    r20_edges = []
    for e in r20_candidates:
        mp = edge_mid(e)
        if any(dist(mp, edge_mid(e2)) < 0.5 for e2 in r20_edges):
            continue
        r20_edges.append(e)

    print(f"[DEBUG] Sharp base edges: {len(solid0.Edges())}")
    print(f"[DEBUG] R20 candidates (Y-axis @ x=100, z=-340/-450): {len(r20_edges)}")

    solid1 = solid0
    if r20_edges:
        out20 = build_fillet(solid0, 20.0, r20_edges)
        if out20 is not None:
            solid1 = out20
            print("[DEBUG] R20 fillet build: DONE")
        else:
            print("[DEBUG] R20 fillet build: FAILED (leaving sharp)")

    # ------------------------------------------------------------
    # Operation 4: R5 on all remaining edges (robust greedy add).
    # We try LINE edges first (outer shape), then CIRCLE edge at bore mouth (x=300).
    # ------------------------------------------------------------
    # Collect candidate LINE edges (exclude tiny)
    line_edges = []
    for e in solid1.Edges():
        try:
            if e.geomType() != "LINE":
                continue
        except Exception:
            continue
        try:
            ln = e.Length()
        except Exception:
            ln = 0.0
        if ln < 0.8:
            continue
        line_edges.append((ln, e))
    line_edges.sort(key=lambda t: -t[0])  # long first
    line_edges = [e for _, e in line_edges]

    # Candidate circles: only the bore mouth at x=300
    circ_edges = []
    for e in solid1.Edges():
        try:
            if e.geomType() != "CIRCLE":
                continue
        except Exception:
            continue
        mp = edge_mid(e)
        if abs(mp[0] - x1) < 0.5:
            circ_edges.append(e)

    candidates = line_edges + circ_edges
    print(f"[DEBUG] R5 candidates: lines={len(line_edges)} circles@x=300={len(circ_edges)} total={len(candidates)}")

    accepted = []
    best_shape = None
    base_for_r5 = solid1

    # Greedy acceptance: keep the last successful shape to avoid extra rebuild at the end
    for i, e in enumerate(candidates):
        trial = build_fillet(base_for_r5, 5.0, accepted + [e])
        if trial is not None:
            accepted.append(e)
            best_shape = trial

    if best_shape is None:
        solid2 = solid1
        print("[DEBUG] R5 fillet build: FAILED (no edges accepted)")
    else:
        solid2 = best_shape
        print(f"[DEBUG] R5 fillet build: DONE (accepted {len(accepted)}/{len(candidates)})")

    # Validation
    bb_out = solid2.BoundingBox()
    try:
        v = solid2.isValid()
    except Exception:
        v = None
    print(f"[DEBUG] Output bbox: x=({bb_out.xmin:.3f},{bb_out.xmax:.3f}) y=({bb_out.ymin:.3f},{bb_out.ymax:.3f}) z=({bb_out.zmin:.3f},{bb_out.zmax:.3f})")
    print(f"[DEBUG] Output valid: {v}")

    return cq.Workplane(obj=solid2)
