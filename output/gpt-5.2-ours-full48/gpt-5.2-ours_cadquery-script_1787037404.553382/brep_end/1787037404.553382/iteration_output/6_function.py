def my_cad_function(args):
    import cadquery as cq
    import os

    if "input_file" not in args:
        raise ValueError("Expected args['input_file']")

    input_file = os.path.expanduser(args["input_file"])
    wp = cq.importers.importStep(input_file)
    imported = wp.val() if hasattr(wp, "val") else wp
    if imported is None:
        raise ValueError("Failed to import STEP")

    # --- Split into solids; operate only on the largest solid (frame) ---
    solids = list(imported.Solids())
    if not solids:
        solids = [imported]

    def safe_volume(s):
        try:
            return float(s.Volume())
        except Exception:
            return 0.0

    solids_sorted = sorted(solids, key=safe_volume, reverse=True)
    main = solids_sorted[0]
    others = solids_sorted[1:]

    print(f"Imported shape valid: {imported.isValid()}")
    print(f"Solids found: {len(solids_sorted)}")
    for i, s in enumerate(solids_sorted[:6]):
        bb = s.BoundingBox()
        print(f"  solid[{i}] vol={safe_volume(s):.3f} bbox=({bb.xlen:.3f},{bb.ylen:.3f},{bb.zlen:.3f})")

    bb = main.BoundingBox()
    print(f"Main (largest) solid bbox: x[{bb.xmin:.3f},{bb.xmax:.3f}] y[{bb.ymin:.3f},{bb.ymax:.3f}] z[{bb.zmin:.3f},{bb.zmax:.3f}]")
    print(f"Main approx size: X={bb.xlen:.3f} Y={bb.ylen:.3f} Z={bb.zlen:.3f}")

    # --- Determine thickness axis as smallest bbox dimension of MAIN solid ---
    lens = {"X": bb.xlen, "Y": bb.ylen, "Z": bb.zlen}
    thickness_axis = min(lens, key=lens.get)
    axis_vecs = {"X": cq.Vector(1, 0, 0), "Y": cq.Vector(0, 1, 0), "Z": cq.Vector(0, 0, 1)}
    ax = axis_vecs[thickness_axis]

    axis_min = {"X": bb.xmin, "Y": bb.ymin, "Z": bb.zmin}[thickness_axis]
    axis_max = {"X": bb.xmax, "Y": bb.ymax, "Z": bb.zmax}[thickness_axis]
    axis_mid = 0.5 * (axis_min + axis_max)

    # Orientation convention for this edit:
    # Treat AXIS_MAX as TOP and AXIS_MIN as BOTTOM.
    print(f"Inferred thickness axis (main solid): {thickness_axis} (len={lens[thickness_axis]:.3f})")
    print(f"Axis min={axis_min:.3f} mid={axis_mid:.3f} max={axis_max:.3f}")
    print("Top/Bottom convention: TOP = axis_max, BOTTOM = axis_min (requested 'bigger radius side' not uniquely detectable from STEP reliably).")

    # --- Parameters (assume STEP units are mm) ---
    offset_mm = 20.0       # 2cm outward offset from inner wall
    support_thk_mm = 5.0   # 0.5cm support thickness
    top_fillet_mm = 2.0    # 0.2cm fillet on TOP shoulder of support only

    # Bottom-edge sharp requirement:
    # We'll *square off* the original bottom by replacing the bottom fillet region
    # with a sharp vertical-wall extrusion down to the original axis_min.
    flatten_height_mm = 12.0  # cut up above existing bottom fillets (>=10mm + margin)

    def coord_of(v: cq.Vector, axis_name: str) -> float:
        return getattr(v, axis_name.lower())

    def minmax_along_bb(bbox, axis_name: str):
        if axis_name == "X":
            return bbox.xmin, bbox.xmax
        if axis_name == "Y":
            return bbox.ymin, bbox.ymax
        return bbox.zmin, bbox.zmax

    def wire_area(w):
        try:
            return abs(cq.Face.makeFromWires(w).Area())
        except Exception:
            return None

    def make_plane_at(axis_name, axis_value, normal_vec: cq.Vector, bbox_for_center):
        cx = 0.5 * (bbox_for_center.xmin + bbox_for_center.xmax)
        cy = 0.5 * (bbox_for_center.ymin + bbox_for_center.ymax)
        cz = 0.5 * (bbox_for_center.zmin + bbox_for_center.zmax)
        if axis_name == "X":
            origin = cq.Vector(axis_value, cy, cz)
        elif axis_name == "Y":
            origin = cq.Vector(cx, axis_value, cz)
        else:
            origin = cq.Vector(cx, cy, axis_value)

        n = normal_vec.normalized()
        ref = cq.Vector(1, 0, 0) if abs(n.dot(cq.Vector(1, 0, 0))) < 0.9 else cq.Vector(0, 0, 1)
        xdir = ref.cross(n)
        if xdir.Length < 1e-9:
            ref = cq.Vector(0, 1, 0)
            xdir = ref.cross(n)
        xdir = xdir.normalized()
        return cq.Plane(origin=origin.toTuple(), xDir=xdir.toTuple(), normal=n.toTuple())

    def section_wires_at(axis_value):
        pl = make_plane_at(thickness_axis, axis_value, ax, bb)
        sec = cq.Workplane(pl).add(main_sq if 'main_sq' in locals() else main).section()
        try:
            sec = sec.consolidateWires()
        except Exception:
            pass
        wires = list(sec.wires().vals())
        scored = []
        for w in wires:
            a = wire_area(w)
            if a is None or a <= 1e-6:
                continue
            scored.append((a, w))
        scored.sort(key=lambda t: t[0], reverse=True)
        return pl, scored

    def offset_wire_on_plane(pl, w, dist, kind="arc"):
        # Use Workplane.offset2D, then pick the resulting wire with largest area
        wpo = cq.Workplane(pl).add(w).toPending().offset2D(dist, kind=kind)
        ws = []
        try:
            ws = list(wpo.wires().vals())
        except Exception:
            ws = []
        best = None
        best_a = -1.0
        for ww in ws:
            aa = wire_area(ww)
            if aa is None:
                continue
            if aa > best_a:
                best_a = aa
                best = ww
        return best, best_a

    # -----------------------------
    # (3) Remove/avoid bottom radii by squaring off the ORIGINAL bottom
    # -----------------------------
    # Clamp flatten height so we don't exceed thickness
    thickness_len = axis_max - axis_min
    if thickness_len <= 1e-6:
        raise ValueError("Degenerate thickness; cannot determine top/bottom.")

    y_flat = axis_min + min(flatten_height_mm, 0.45 * thickness_len)
    print(f"Bottom squaring: axis_min={axis_min:.3f}, y_flat={y_flat:.3f} (flatten_height_mm={flatten_height_mm:.3f})")

    # Keep the portion above y_flat via intersection with a big box
    margin = max(10.0, 0.02 * max(bb.xlen, bb.ylen, bb.zlen))
    cx = 0.5 * (bb.xmin + bb.xmax)
    cy = 0.5 * (bb.ymin + bb.ymax)
    cz = 0.5 * (bb.zmin + bb.zmax)

    # Box dimensions and center depend on thickness axis
    if thickness_axis == "X":
        x0, x1 = y_flat, axis_max + margin
        box_x = (x1 - x0)
        box_y = bb.ylen + 2 * margin
        box_z = bb.zlen + 2 * margin
        box_c = (0.5 * (x0 + x1), cy, cz)
    elif thickness_axis == "Y":
        y0, y1 = y_flat, axis_max + margin
        box_x = bb.xlen + 2 * margin
        box_y = (y1 - y0)
        box_z = bb.zlen + 2 * margin
        box_c = (cx, 0.5 * (y0 + y1), cz)
    else:
        z0, z1 = y_flat, axis_max + margin
        box_x = bb.xlen + 2 * margin
        box_y = bb.ylen + 2 * margin
        box_z = (z1 - z0)
        box_c = (cx, cy, 0.5 * (z0 + z1))

    keeper_box = cq.Workplane("XY").box(box_x, box_y, box_z).translate(box_c)
    main_top = main.intersect(keeper_box.val())

    # Get outer/inner wires at y_flat from the (top) body; should be past fillet tangent
    pl_flat = make_plane_at(thickness_axis, y_flat, ax, bb)
    sec_flat = cq.Workplane(pl_flat).add(main_top).section()
    try:
        sec_flat = sec_flat.consolidateWires()
    except Exception:
        pass

    wires_flat = list(sec_flat.wires().vals())
    scored_flat = []
    for w in wires_flat:
        a = wire_area(w)
        if a is None or a <= 1e-6:
            continue
        scored_flat.append((a, w))
    scored_flat.sort(key=lambda t: t[0], reverse=True)
    print(f"Section @ y_flat {thickness_axis}={y_flat:.3f}: wires={len(scored_flat)} areas={[round(t[0],1) for t in scored_flat[:6]]}")

    if len(scored_flat) < 2:
        print("WARNING: Could not find 2 section wires at y_flat; skipping bottom squaring.")
        main_sq = main
    else:
        outer_flat = scored_flat[0][1]
        inner_flat = scored_flat[1][1]
        try:
            slab_face = cq.Face.makeFromWires(outer_flat, [inner_flat])
            # Extrude DOWN to axis_min (sharp), along -ax
            slab_h = (y_flat - axis_min)
            slab = cq.Workplane(pl_flat).add(slab_face).extrude(slab_h)
            main_sq = cq.Workplane(obj=main_top).union(slab).val()
            print(f"Bottom squaring applied: rebuilt sharp bottom over height {slab_h:.3f}mm")
        except Exception as e:
            print(f"WARNING: Bottom squaring failed ({e}); keeping original main.")
            main_sq = main

    # -----------------------------
    # (2) Add bottom support step from inner opening offset outward by 20mm, extrude 5mm down
    # -----------------------------
    # Derive inner opening wire from mid-thickness section (more stable), then translate to axis_min
    pl_mid = make_plane_at(thickness_axis, axis_mid, ax, bb)
    sec_mid = cq.Workplane(pl_mid).add(main_sq).section()
    try:
        sec_mid = sec_mid.consolidateWires()
    except Exception:
        pass

    wires_mid = list(sec_mid.wires().vals())
    scored_mid = []
    for w in wires_mid:
        a = wire_area(w)
        if a is None or a <= 1e-6:
            continue
        scored_mid.append((a, w))
    scored_mid.sort(key=lambda t: t[0], reverse=True)
    print(f"Section @ mid {thickness_axis}={axis_mid:.3f}: usable_wires={len(scored_mid)} top_areas={[round(t[0],1) for t in scored_mid[:6]]}")

    if len(scored_mid) < 2:
        raise ValueError("Could not derive inner opening: mid-thickness section produced <2 usable wires.")

    inner_wire = scored_mid[1][1]

    # Translate inner wire to the support TOP plane at axis_min (the interface plane)
    delta = (axis_min - axis_mid)
    inner_wire = inner_wire.translate(ax.multiply(delta))

    base_a = wire_area(inner_wire) or 0.0
    print(f"Inner opening wire area (at support interface plane): {base_a:.3f}")

    # Create support sketch plane at axis_min; extrude along -ax
    plane_support_top = make_plane_at(thickness_axis, axis_min, ax.multiply(-1), bb)

    # Offset outward (choose direction that increases area)
    w_pos, a_pos = offset_wire_on_plane(plane_support_top, inner_wire, +offset_mm, kind="arc")
    w_neg, a_neg = offset_wire_on_plane(plane_support_top, inner_wire, -offset_mm, kind="arc")
    print(f"Offset test (support): +{offset_mm:.3f}mm area={a_pos:.3f} ; -{offset_mm:.3f}mm area={a_neg:.3f}")

    candidates = []
    if w_pos is not None:
        candidates.append((a_pos, +offset_mm, w_pos))
    if w_neg is not None:
        candidates.append((a_neg, -offset_mm, w_neg))
    if not candidates:
        raise ValueError("Failed to offset inner opening wire in either direction for support.")
    candidates.sort(key=lambda t: t[0], reverse=True)
    offset_outer = candidates[0][2]
    chosen_dist = candidates[0][1]
    chosen_area = candidates[0][0]
    print(f"Chosen support offset: dist={chosen_dist:.3f}mm area={chosen_area:.3f}")

    # Build support annulus and extrude DOWN by 5mm
    ring_face = cq.Face.makeFromWires(offset_outer, [inner_wire])
    support = cq.Workplane(plane_support_top).add(ring_face).extrude(support_thk_mm)  # downwards

    # -----------------------------
    # (4) Apply fillet ONLY to TOP-side shoulder edges of support (at axis_min), keep bottom sharp
    # -----------------------------
    sup_shape = support.val()
    tol_edge = max(0.05, top_fillet_mm * 0.1)

    def edge_on_plane(e, axis_name, target_coord):
        try:
            for v in e.Vertices():
                if abs(coord_of(v.Center(), axis_name) - target_coord) > tol_edge:
                    return False
            return True
        except Exception:
            return False

    top_edges = [e for e in sup_shape.Edges() if edge_on_plane(e, thickness_axis, axis_min)]
    print(f"Support shoulder edges selected for fillet @ axis_min: {len(top_edges)}")

    if top_edges:
        support = cq.Workplane(obj=sup_shape).edges().filter(lambda e: e in top_edges).fillet(top_fillet_mm)
    else:
        print("WARNING: No support shoulder edges found to fillet; skipping fillet.")

    # -----------------------------
    # Final union and recombine
    # -----------------------------
    edited_main = cq.Workplane(obj=main_sq).union(support).val()

    if others:
        comp = cq.Compound.makeCompound([edited_main] + others)
        result = cq.Workplane(obj=comp)
    else:
        result = cq.Workplane(obj=edited_main)

    return result
