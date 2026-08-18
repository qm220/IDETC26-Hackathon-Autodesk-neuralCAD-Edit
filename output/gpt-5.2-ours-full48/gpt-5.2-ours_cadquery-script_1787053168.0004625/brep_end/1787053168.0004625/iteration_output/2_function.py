def my_cad_function(args):
    import cadquery as cq
    import os

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
    # Recreate functional features (bore + side pocket)
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

    # Pocket (as per planning numbers; opens on y=230 side)
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
    # Fillets per rules:
    #   - R20 on horizontal shoulder wing edges at x=100 on the TOP (z=-340)
    #   - R5 on remaining OUTER intersection edges of the main prismatic body
    #     (avoid pocket edges to prevent fillet failures)
    # ------------------------------------------------------------
    tol_plane = 0.35
    tol_span = 0.70

    def _on_any(v, arr, tol=tol_plane):
        return any(abs(v - a) <= tol for a in arr)

    # ---- R20 selection (top shoulder "wings")
    def is_r20_shoulder_top_wing_edge(e):
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

        # Edge should lie on x=100 and z=-340, and run along Y
        if abs(cx - x_shoulder) > tol_plane:
            return False
        if abs(cz - arm_z_max) > tol_plane:
            return False
        if dx > tol_span or dz > tol_span:
            return False

        # wing length is ~30mm (from 200->230 and 290->320)
        if not (20.0 <= dy <= 40.0):
            return False

        return True

    # Apply R20
    try:
        wp = cq.Workplane(obj=result.val())
        sel20 = wp.edges().filter(is_r20_shoulder_top_wing_edge)
        e20 = sel20.vals()
        print(f"[DEBUG] R20 candidate edges (top shoulder wings): {len(e20)}")
        if len(e20) > 0:
            result = sel20.fillet(20.0)
            print("[DEBUG] Applied R20 fillet.")
        else:
            print("[WARN] No R20 edges found; skipping R20 fillet.")
    except Exception as e:
        print("[WARN] R20 fillet failed:", e)

    # ---- R5 selection (outer main-body edges only)
    x_planes = [x0, x_shoulder, x_tip]
    y_planes = [head_y_min, arm_y_min, arm_y_max, head_y_max]
    z_planes = [head_z_max, arm_z_min, head_z_min]  # -340, -445, -450

    R5 = 5.0
    min_len = 2.0 * R5 + 0.25  # avoid tiny edges (e.g., 5mm step edges) that often fail

    def is_r5_outer_edge(e):
        try:
            if e.geomType() != "LINE":
                return False
        except Exception:
            return False

        try:
            if e.Length() < min_len:
                return False
        except Exception:
            pass

        bb = e.BoundingBox()
        dx = bb.xmax - bb.xmin
        dy = bb.ymax - bb.ymin
        dz = bb.zmax - bb.zmin

        cx = 0.5 * (bb.xmin + bb.xmax)
        cy = 0.5 * (bb.ymin + bb.ymax)
        cz = 0.5 * (bb.zmin + bb.zmax)

        # A line edge should have two near-constant coordinates (two small spans)
        const_axes = []
        if dx < tol_span:
            const_axes.append(("x", cx))
        if dy < tol_span:
            const_axes.append(("y", cy))
        if dz < tol_span:
            const_axes.append(("z", cz))
        if len(const_axes) < 2:
            return False

        allowed = {"x": x_planes, "y": y_planes, "z": z_planes}
        good = 0
        for ax, v in const_axes:
            if _on_any(v, allowed[ax]):
                good += 1

        # Keep only edges that are intersection of two global outer planes
        # (this excludes pocket perimeter edges on z=-374/-405, x=125/168, y=280, etc.)
        return good >= 2

    # Apply R5 (in two passes for robustness)
    try:
        wp5 = cq.Workplane(obj=result.val())
        sel5 = wp5.edges().filter(is_r5_outer_edge)
        e5 = sel5.vals()
        print(f"[DEBUG] R5 candidate edges (outer only): {len(e5)}")
        if len(e5) > 0:
            result = sel5.fillet(R5)
            print("[DEBUG] Applied R5 fillet (outer-only selection).")
        else:
            print("[WARN] No R5 edges found; skipping R5 fillet.")
    except Exception as e:
        print("[WARN] R5 fillet failed (outer-only set):", e)
        # Fallback: try only the longest edges
        try:
            def is_r5_outer_edge_long(e):
                if not is_r5_outer_edge(e):
                    return False
                try:
                    return e.Length() >= 20.0
                except Exception:
                    return False

            wp5b = cq.Workplane(obj=result.val())
            sel5b = wp5b.edges().filter(is_r5_outer_edge_long)
            e5b = sel5b.vals()
            print(f"[DEBUG] R5 fallback candidate edges (outer-only, >=20mm): {len(e5b)}")
            if len(e5b) > 0:
                result = sel5b.fillet(R5)
                print("[DEBUG] Applied R5 fillet (fallback, long edges only).")
        except Exception as e2:
            print("[WARN] R5 fillet failed (fallback):", e2)

    out = result.val() if hasattr(result, "val") else result
    bb2 = out.BoundingBox()
    print(f"[DEBUG] Output bbox: x=({bb2.xmin:.3f},{bb2.xmax:.3f}) y=({bb2.ymin:.3f},{bb2.ymax:.3f}) z=({bb2.zmin:.3f},{bb2.zmax:.3f})")

    return result
