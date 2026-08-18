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

    # Prefer a slender part near x~0, y~-40, z span ~20
    def score(item):
        i, s, bb, (cx, cy, cz), (dx, dy, dz) = item
        # penalties
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

    # --- Extract reference: main cylinder radius, and top lead-in effective (dr, h) ---
    faces = list(heat_s.Faces())
    cyl_faces = []
    cone_faces = []
    for f in faces:
        gt = None
        try:
            gt = f.geomType()
        except Exception:
            gt = "?"
        if gt == "CYLINDER":
            try:
                R = f._geomAdaptor().Cylinder().Radius()
                cyl_faces.append((R, f))
            except Exception:
                pass
        elif gt == "CONE":
            cone_faces.append(f)

    print(f"Heatbreak faces: total={len(faces)} cyl={len(cyl_faces)} cone={len(cone_faces)}")
    if not cyl_faces:
        print("WARNING: No cylindrical faces found on selected solid; returning original.")
        return shape_wp

    cyl_faces.sort(key=lambda t: t[0], reverse=True)
    main_R, main_cyl_face = cyl_faces[0]
    print(f"Main cylinder radius R={main_R:.6f}")

    zmax = heat_bb.zmax

    # Find z positions of circular edges on the main cylinder (top transition and bottom seat)
    cyl_circle_edges = []
    for e in main_cyl_face.Edges():
        try:
            if e.geomType() == "CIRCLE":
                eb = e.BoundingBox()
                # circle edges should have essentially constant z
                zc = 0.5 * (eb.zmin + eb.zmax)
                try:
                    r_e = e._geomAdaptor().Circle().Radius()
                except Exception:
                    r_e = None
                cyl_circle_edges.append((zc, r_e, e))
        except Exception:
            continue

    cyl_circle_edges.sort(key=lambda t: t[0])
    if len(cyl_circle_edges) < 2:
        print("WARNING: Could not find both top/bottom circular edges on main cylinder; using fallback chamfer.")
        z_bottom = heat_bb.zmin
        chamfer_d1 = 0.5
        chamfer_d2 = 0.5
    else:
        z_bottom, _, bottom_circle_edge = cyl_circle_edges[0]
        # top edge of cylinder is the highest z circle edge still below zmax
        top_candidates = [t for t in cyl_circle_edges if t[0] < (zmax - 1e-4)]
        if not top_candidates:
            z_transition = cyl_circle_edges[-1][0]
        else:
            z_transition = top_candidates[-1][0]

        # Find radius at the very top opening by looking for a cone edge at zmax (if present)
        r_top = None
        z_top_edge = None
        best_dz = 1e9
        for cf in cone_faces:
            for e in cf.Edges():
                try:
                    if e.geomType() != "CIRCLE":
                        continue
                    eb = e.BoundingBox()
                    zc = 0.5 * (eb.zmin + eb.zmax)
                    dz = abs(zc - zmax)
                    if dz < best_dz:
                        best_dz = dz
                        z_top_edge = zc
                        try:
                            r_top = e._geomAdaptor().Circle().Radius()
                        except Exception:
                            r_top = None
                except Exception:
                    continue

        # Compute effective top lead-in as (radial reduction, axial height)
        h = float(zmax - z_transition)
        if r_top is None:
            # fallback: assume 45deg small chamfer ~0.5mm
            dr = 0.5
            print("WARNING: Could not measure top cone/top radius; using fallback dr=0.5")
        else:
            dr = float(main_R - r_top)

        # sanity / fallback
        if h <= 1e-6 or dr <= 1e-6:
            print(f"WARNING: Derived lead-in seems invalid (dr={dr:.6f}, h={h:.6f}); using fallback 0.5/0.5")
            chamfer_d1 = 0.5
            chamfer_d2 = 0.5
        else:
            chamfer_d1 = dr
            chamfer_d2 = h

        print(f"Measured top lead-in: zmax={zmax:.6f}, z_transition={z_transition:.6f}, h={h:.6f}, r_top={r_top}, dr={dr:.6f}")
        print(f"Bottom circle z={z_bottom:.6f}")

    # --- Apply chamfer on the lower edge of the main cylinder (insertion lead-in) ---
    # Use a NearestToPoint selector to target the bottom circular edge on the main cylinder
    # Point chosen on the OD at the bottom z.
    pick_pt = (hc_x + float(main_R), hc_y, float(z_bottom))
    print(f"Chamfer pick point: ({pick_pt[0]:.6f}, {pick_pt[1]:.6f}, {pick_pt[2]:.6f})")
    print(f"Applying chamfer(d1={chamfer_d1:.6f}, d2={chamfer_d2:.6f})")

    try:
        sel = cq.selectors.NearestToPointSelector(pick_pt)
        modified_heat = (
            cq.Workplane(obj=heat_s)
            .edges(sel)
            .chamfer(chamfer_d1, chamfer_d2)
            .val()
        )
    except Exception as e:
        print(f"ERROR: Chamfer operation failed: {e}")
        import traceback
        traceback.print_exc()
        return shape_wp

    # --- Rebuild compound with modified solid replacing original ---
    new_solids = []
    for i, s in enumerate(solids):
        new_solids.append(modified_heat if i == heat_i else s)

    result = cq.Compound.makeCompound(new_solids)
    print("Rebuilt compound with modified heatbreak solid.")
    return result
