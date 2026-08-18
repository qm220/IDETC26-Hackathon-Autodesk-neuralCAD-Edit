def my_cad_function(args):
    import cadquery as cq
    import os

    # ------------------------------------------------------------
    # 1) Inspect the incoming STEP (debug / reference extraction)
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
    # 2) Rebuild a symmetric, sharp-edged base solid (no chamfers/radii)
    #    Using dimensions inferred from model.json planning notes.
    # ------------------------------------------------------------
    # Key planes from planning stage
    x0, x_shoulder, x_tip = 0.0, 100.0, 300.0

    # Head (larger section)
    head_x_len = x_shoulder - x0               # 100
    head_y_min, head_y_max = 200.0, 320.0      # 120 wide
    head_z_min, head_z_max = -450.0, -340.0    # 110 tall

    # Arm (narrow section) - force symmetry about y=260 => y=[230,290]
    arm_x_len = x_tip - x_shoulder             # 200
    arm_y_min, arm_y_max = 230.0, 290.0        # 60 wide (symmetric)
    arm_z_min, arm_z_max = -445.0, -340.0      # 105 tall

    # Build head and arm as sharp boxes
    head = (
        cq.Workplane("XY")
        .box(head_x_len, head_y_max - head_y_min, head_z_max - head_z_min, centered=True)
        .translate((
            (x0 + x_shoulder) / 2.0,
            (head_y_min + head_y_max) / 2.0,
            (head_z_min + head_z_max) / 2.0,
        ))
    )

    arm = (
        cq.Workplane("XY")
        .box(arm_x_len, arm_y_max - arm_y_min, arm_z_max - arm_z_min, centered=True)
        .translate((
            (x_shoulder + x_tip) / 2.0,
            (arm_y_min + arm_y_max) / 2.0,
            (arm_z_min + arm_z_max) / 2.0,
        ))
    )

    result = head.union(arm)

    # ------------------------------------------------------------
    # 3) Add/cut functional features that are not "chamfers/radii":
    #    - axial blind bore (X-direction) from x=100 to x=300
    #    - bottom pocket (side-opening slot per planning dims)
    # ------------------------------------------------------------
    # Bore
    bore_r = 14.142  # per planning stage
    bore_yc = 260.0
    bore_zc = (arm_z_min + arm_z_max) / 2.0  # centered in arm thickness

    bore_plane = cq.Plane(origin=(x_shoulder, 0, 0), xDir=(0, 1, 0), normal=(1, 0, 0))  # YZ at x=100
    bore = (
        cq.Workplane(bore_plane)
        .center(bore_yc, bore_zc)
        .circle(bore_r)
        .extrude(x_tip - x_shoulder)  # +X direction to x=300
    )
    result = result.cut(bore)

    # Bottom pocket / recess (interpreted as a side-opening recess spanning y=230..280)
    px0, px1 = 125.350920, 168.336333
    py0, py1 = 230.0, 280.0
    pz0, pz1 = -405.071245, -374.121747
    pocket = (
        cq.Workplane("XY")
        .box(px1 - px0, py1 - py0, pz1 - pz0, centered=True)
        .translate(((px0 + px1) / 2.0, (py0 + py1) / 2.0, (pz0 + pz1) / 2.0))
    )
    result = result.cut(pocket)

    # ------------------------------------------------------------
    # 4) Apply new fillets per rules:
    #    - R20 on *horizontal* (Y-direction) shoulder edges at x=100,
    #      specifically the two "wing" segments created by the head being wider than the arm.
    #    - R5 on remaining (eligible) edges
    # ------------------------------------------------------------
    import cadquery.selectors as cqs

    def _is_r20_shoulder_edge(e):
        """Select only the Y-parallel shoulder edges at x=100 on the width step wings.
        We avoid the y-span=60 edge (arm width) and target the y-span~30 wing edges.
        """
        bb = e.BoundingBox()
        cx = 0.5 * (bb.xmin + bb.xmax)
        dx = bb.xmax - bb.xmin
        dy = bb.ymax - bb.ymin
        dz = bb.zmax - bb.zmin

        # near shoulder plane
        if abs(cx - x_shoulder) > 0.25:
            return False
        # line-like in X and Z, long in Y
        if dx > 0.6 or dz > 0.6:
            return False
        # wing segments are ~30mm in Y
        if not (20.0 <= dy <= 40.0):
            return False
        return True

    # R20 fillet first
    try:
        result = result.edges(cqs.FilterSelector(_is_r20_shoulder_edge)).fillet(20.0)
        print("[DEBUG] Applied R20 fillets on shoulder wing edges.")
    except Exception as e:
        print("[WARN] R20 fillet failed:", e)

    # R5 on remaining edges (skip tiny edges to reduce fillet failures)
    def _is_r5_candidate(e):
        try:
            if e.geomType() != "LINE":
                return False
            if e.Length() < 12.0:  # avoid 5mm-tall step edges etc.
                return False
            return True
        except Exception:
            return False

    try:
        result = result.edges(cqs.FilterSelector(_is_r5_candidate)).fillet(5.0)
        print("[DEBUG] Applied R5 fillets on remaining eligible linear edges.")
    except Exception as e:
        print("[WARN] R5 fillet failed:", e)

    # Final debug
    sh2 = result.val() if hasattr(result, "val") else result
    bb2 = sh2.BoundingBox()
    print(f"[DEBUG] Output bbox: x=({bb2.xmin:.3f},{bb2.xmax:.3f}) y=({bb2.ymin:.3f},{bb2.ymax:.3f}) z=({bb2.zmin:.3f},{bb2.zmax:.3f})")

    return result
