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

    # Head (larger section) - per planning
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

    # Bottom rectangular pocket
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
    #   - R20 on the two shoulder "wing" horizontal edges (Y-parallel) at x=100 (top and bottom)
    #   - R5 on all other remaining LINE edges
    # ------------------------------------------------------------
    tol_x = 0.25
    tol_line = 0.6

    def is_r20_shoulder_wing_edge(e):
        # Target: LINE edges parallel to Y (dx~0, dz~0), centered at x=100,
        # and with Y-span ~30mm (the shoulder wings caused by width step 120->60)
        bb = e.BoundingBox()
        cx = 0.5 * (bb.xmin + bb.xmax)
        dx = bb.xmax - bb.xmin
        dy = bb.ymax - bb.ymin
        dz = bb.zmax - bb.zmin

        if abs(cx - x_shoulder) > tol_x:
            return False
        if dx > tol_line or dz > tol_line:
            return False
        # wing length is ~30
        if not (20.0 <= dy <= 40.0):
            return False
        try:
            return e.geomType() == "LINE"
        except Exception:
            return True

    # Apply R20
    try:
        wp = cq.Workplane(obj=result.val())
        sel20 = wp.edges().filter(is_r20_shoulder_wing_edge)
        e20 = sel20.vals()
        print(f"[DEBUG] R20 candidate edges: {len(e20)}")
        if len(e20) > 0:
            result = sel20.fillet(20.0)
            print("[DEBUG] Applied R20 fillet.")
        else:
            print("[WARN] No R20 edges found; skipping R20 fillet.")
    except Exception as e:
        print("[WARN] R20 fillet failed:", e)

    # Apply R5 to all remaining LINE edges (after R20, those edges are no longer LINE)
    def is_line_edge(e):
        try:
            return e.geomType() == "LINE"
        except Exception:
            return False

    try:
        wp2 = cq.Workplane(obj=result.val())
        sel5 = wp2.edges().filter(is_line_edge)
        e5 = sel5.vals()
        print(f"[DEBUG] R5 candidate LINE edges: {len(e5)}")
        if len(e5) > 0:
            result = sel5.fillet(5.0)
            print("[DEBUG] Applied R5 fillet to remaining LINE edges.")
        else:
            print("[WARN] No R5 edges found; skipping R5 fillet.")
    except Exception as e:
        # Fallback: avoid tiny edges that can cause fillet failure
        print("[WARN] R5 fillet failed (full set):", e)
        try:
            def is_line_edge_long(e):
                try:
                    return e.geomType() == "LINE" and e.Length() >= 11.0
                except Exception:
                    return False
            wp2 = cq.Workplane(obj=result.val())
            sel5b = wp2.edges().filter(is_line_edge_long)
            e5b = sel5b.vals()
            print(f"[DEBUG] R5 fallback candidate LINE edges (>=11mm): {len(e5b)}")
            if len(e5b) > 0:
                result = sel5b.fillet(5.0)
                print("[DEBUG] Applied R5 fillet (fallback selection).")
        except Exception as e2:
            print("[WARN] R5 fillet failed (fallback):", e2)

    # Final debug
    out = result.val() if hasattr(result, "val") else result
    bb2 = out.BoundingBox()
    print(f"[DEBUG] Output bbox: x=({bb2.xmin:.3f},{bb2.xmax:.3f}) y=({bb2.ymin:.3f},{bb2.ymax:.3f}) z=({bb2.zmin:.3f},{bb2.zmax:.3f})")

    return result
