def my_cad_function(args):
    import cadquery as cq
    import os

    input_file = os.path.expanduser(args.get("input_file", ""))
    shape_wp = cq.importers.importStep(input_file)
    base_shape = shape_wp.val() if hasattr(shape_wp, "val") else shape_wp

    solids = list(base_shape.Solids())
    print(f"Loaded STEP: {input_file}")
    print(f"Total solids: {len(solids)}")

    # --- Identify heatbreak / standoff solid (S06) by bbox heuristics ---
    candidates = []
    for i, s in enumerate(solids):
        bb = s.BoundingBox()
        cx, cy, cz = bb.center.x, bb.center.y, bb.center.z
        dims = (bb.xlen, bb.ylen, bb.zlen)
        candidates.append((i, s, bb, (cx, cy, cz), dims))
        print(
            f"Solid[{i}] center=({cx:.3f},{cy:.3f},{cz:.3f}) dims=({dims[0]:.3f},{dims[1]:.3f},{dims[2]:.3f}) "
            f"zrange=({bb.zmin:.3f},{bb.zmax:.3f}) yrange=({bb.ymin:.3f},{bb.ymax:.3f})"
        )

    def score(item):
        i, s, bb, (cx, cy, cz), (dx, dy, dz) = item
        return (
            abs(cx - 0.0) * 2.0
            + abs(cy - (-40.0)) * 1.0
            + abs(dz - 20.0) * 0.5
            + max(0.0, dx - 15.0) * 5.0
            + max(0.0, dy - 15.0) * 5.0
        )

    candidates_sorted = sorted(candidates, key=score)
    heat_i, heat_s, heat_bb, (hc_x, hc_y, hc_z), (hdx, hdy, hdz) = candidates_sorted[0]
    print(f"Selected heatbreak candidate: Solid[{heat_i}] score={score(candidates_sorted[0]):.3f}")

    # --- Helpers ---
    def circle_edge_info(e):
        """Return (z, r) for circle edge e; else None."""
        try:
            if e.geomType() != "CIRCLE":
                return None
            eb = e.BoundingBox()
            zc = 0.5 * (eb.zmin + eb.zmax)
            r = e._geomAdaptor().Circle().Radius()
            return float(zc), float(r)
        except Exception:
            return None

    def edges_circles_on_face(face):
        out = []
        for e in face.Edges():
            info = circle_edge_info(e)
            if info:
                zc, r = info
                out.append((zc, r, e))
        return out

    def group_max_radius_by_z(zr_list, z_tol=1e-3):
        """Given list of (z,r,edge), group by z within tol and keep max r in each group."""
        groups = []
        for z, r, e in sorted(zr_list, key=lambda t: t[0]):
            placed = False
            for g in groups:
                if abs(g[0] - z) <= z_tol:
                    # keep max radius representative
                    if r > g[1]:
                        g[0], g[1], g[2] = z, r, e
                    placed = True
                    break
            if not placed:
                groups.append([z, r, e])
        return [(g[0], g[1], g[2]) for g in groups]

    def measure_bottom_chamfer(solid, z_ref, main_R, search_up=10.0):
        """Try to find the newly created chamfer cone near z_ref and measure (axial, dr)."""
        cone_faces = []
        for f in solid.Faces():
            try:
                if f.geomType() == "CONE":
                    cone_faces.append(f)
            except Exception:
                pass

        best = None
        for cf in cone_faces:
            bb = cf.BoundingBox()
            # cone should be near the bottom edge region
            if bb.zmax < (z_ref - 1e-3) or bb.zmin > (z_ref + search_up):
                continue
            # require it to intersect main radius somewhere (edge radius near main_R)
            circles = edges_circles_on_face(cf)
            if not circles:
                continue
            # group by z, keep outermost radius per z
            groups = group_max_radius_by_z(circles, z_tol=1e-3)
            # (outer chamfer should include an edge near main_R)
            if not any(abs(r - main_R) < 0.05 for (z, r, _) in groups):
                continue

            groups_sorted = sorted(groups, key=lambda t: t[0])
            z_lo, r_lo, _ = groups_sorted[0]
            z_hi, r_hi, _ = groups_sorted[-1]
            axial = float(z_hi - z_lo)
            dr_meas = float(r_hi - r_lo)

            # candidate score: closest to z_ref and positive measures
            if axial <= 1e-6 or dr_meas <= 1e-6:
                continue
            s = abs(bb.zmin - z_ref)
            if best is None or s < best[0]:
                best = (s, axial, dr_meas, (z_lo, r_lo, z_hi, r_hi))

        if best is None:
            return None
        _, axial, dr_meas, detail = best
        return {"axial": axial, "dr": dr_meas, "detail": detail}

    # --- Find main outer cylinder face (largest radius, and prefer tall span) ---
    cyl_faces = []
    for f in heat_s.Faces():
        try:
            if f.geomType() == "CYLINDER":
                R = f._geomAdaptor().Cylinder().Radius()
                bb = f.BoundingBox()
                zspan = bb.zmax - bb.zmin
                cyl_faces.append((float(R), float(zspan), f))
        except Exception:
            pass

    print(f"Heatbreak cylindrical faces found: {len(cyl_faces)}")
    if not cyl_faces:
        print("WARNING: No cylindrical faces found on selected heatbreak; returning original.")
        return shape_wp

    # Sort by radius then z-span
    cyl_faces.sort(key=lambda t: (t[0], t[1]), reverse=True)
    main_R, main_zspan, main_cyl_face = cyl_faces[0]
    print(f"Main cylinder: R={main_R:.6f}, zspan={main_zspan:.6f}")

    # --- Determine bottom edge (lower edge of main cylinder section) ---
    cyl_circles = edges_circles_on_face(main_cyl_face)
    cyl_circles_r = [(z, r, e) for (z, r, e) in cyl_circles if abs(r - main_R) < 0.02]
    cyl_circles_r = group_max_radius_by_z(cyl_circles_r, z_tol=1e-4)
    if len(cyl_circles_r) < 2:
        print("WARNING: Could not find >=2 circle edges at main radius on main cylinder. Using bbox zmin as reference.")
        z_bottom = float(heat_bb.zmin)
        z_top_transition_guess = float(heat_bb.zmax)
    else:
        cyl_circles_r_sorted = sorted(cyl_circles_r, key=lambda t: t[0])
        z_bottom = float(cyl_circles_r_sorted[0][0])
        z_top_transition_guess = float(cyl_circles_r_sorted[-1][0])

    print(f"Main cylinder circle z levels (at ~main_R): {[round(t[0],4) for t in sorted(cyl_circles_r, key=lambda x:x[0])]}" )
    print(f"Chosen z_bottom(main cylinder lower edge)={z_bottom:.6f}")

    # --- Measure top lead-in (match existing top chamfer/taper on OD) ---
    cone_faces = []
    for f in heat_s.Faces():
        try:
            if f.geomType() == "CONE":
                cone_faces.append(f)
        except Exception:
            pass

    z_transition = None
    lead_cone = None

    if cyl_circles_r:
        z_transition = float(max(z for (z, r, e) in cyl_circles_r))

    if z_transition is not None and cone_faces:
        best = None
        for cf in cone_faces:
            circles_cf = edges_circles_on_face(cf)
            for (z, r, e) in circles_cf:
                if abs(r - main_R) < 0.02 and abs(z - z_transition) < 1e-3:
                    bb = cf.BoundingBox()
                    ext = bb.zmax - z_transition
                    s = -ext
                    if best is None or s < best[0]:
                        best = (s, cf)
        if best is not None:
            lead_cone = best[1]

    chamfer_dr = None
    chamfer_h = None

    if lead_cone is not None and z_transition is not None:
        circles = edges_circles_on_face(lead_cone)
        groups = group_max_radius_by_z(circles, z_tol=1e-4)
        above = [(z, r, e) for (z, r, e) in groups if z >= (z_transition - 1e-4)]
        if above:
            z_top = max(z for (z, r, e) in above)
            at_top = [(z, r, e) for (z, r, e) in above if abs(z - z_top) < 1e-3]
            r_top_outer = max(r for (z, r, e) in at_top)
            chamfer_h = float(z_top - z_transition)
            chamfer_dr = float(main_R - r_top_outer)
            print(
                f"Top lead-in from adjacent cone: z_transition={z_transition:.6f}, z_top={z_top:.6f}, "
                f"r_top_outer={r_top_outer:.6f}, dr={chamfer_dr:.6f}, h={chamfer_h:.6f}"
            )

    if chamfer_dr is None or chamfer_h is None or chamfer_dr <= 1e-6 or chamfer_h <= 1e-6:
        chamfer_dr = 0.3
        chamfer_h = 0.3
        print("WARNING: Could not robustly measure top lead-in; using fallback chamfer_dr=0.3, chamfer_h=0.3")

    # --- Apply chamfer to lower edge of main cylinder ---
    pick_pt = (hc_x + float(main_R), hc_y, float(z_bottom))
    print(f"Chamfer target pick point (OD @ lower edge): ({pick_pt[0]:.6f}, {pick_pt[1]:.6f}, {pick_pt[2]:.6f})")

    def apply_chamfer(d1, d2):
        sel = cq.selectors.NearestToPointSelector(pick_pt)
        return cq.Workplane(obj=heat_s).edges(sel).chamfer(float(d1), float(d2)).val()

    print(f"Attempt chamfer(d1={chamfer_dr:.6f}, d2={chamfer_h:.6f})")
    try:
        modified_heat = apply_chamfer(chamfer_dr, chamfer_h)
    except Exception as e:
        print(f"ERROR: Chamfer attempt 1 failed: {e}")
        import traceback
        traceback.print_exc()
        return shape_wp

    meas = measure_bottom_chamfer(modified_heat, z_ref=z_bottom, main_R=main_R, search_up=10.0)
    if meas is not None:
        axial = meas["axial"]
        dr_meas = meas["dr"]
        print(f"Measured created bottom chamfer approx: axial={axial:.6f}, dr={dr_meas:.6f}, detail={meas['detail']}")
        err_direct = abs(axial - chamfer_h) + abs(dr_meas - chamfer_dr)
        err_swapped = abs(axial - chamfer_dr) + abs(dr_meas - chamfer_h)
        print(f"Chamfer orientation check: err_direct={err_direct:.6f}, err_swapped={err_swapped:.6f}")
        if err_swapped + 1e-3 < err_direct:
            print("Detected swapped chamfer distances; redoing with swapped (d1=h, d2=dr).")
            try:
                modified_heat = apply_chamfer(chamfer_h, chamfer_dr)
            except Exception as e:
                print(f"ERROR: Chamfer attempt 2 (swapped) failed: {e}")
                import traceback
                traceback.print_exc()
                return shape_wp

    # --- Rebuild compound with modified solid replacing original ---
    new_solids = [modified_heat if i == heat_i else s for i, s in enumerate(solids)]
    result = cq.Compound.makeCompound(new_solids)
    print("Rebuilt compound with modified heatbreak solid.")
    return result
