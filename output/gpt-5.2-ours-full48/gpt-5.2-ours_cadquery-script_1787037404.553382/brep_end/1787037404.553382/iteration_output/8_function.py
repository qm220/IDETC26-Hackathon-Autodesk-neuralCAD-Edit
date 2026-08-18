def my_cad_function(args):
    import cadquery as cq
    import os, math

    if "input_file" not in args:
        raise ValueError("Expected args['input_file']")

    input_file = os.path.expanduser(args["input_file"])
    wp_in = cq.importers.importStep(input_file)
    shape = wp_in.val() if hasattr(wp_in, "val") else wp_in
    if shape is None:
        raise ValueError("Failed to import STEP")

    solids = list(shape.Solids())
    if not solids:
        # sometimes import returns a single solid-like shape
        solids = [shape]

    def safe_volume(s):
        try:
            return float(s.Volume())
        except Exception:
            return 0.0

    solids_sorted = sorted(solids, key=safe_volume, reverse=True)
    main = solids_sorted[0]
    others = solids_sorted[1:]

    print(f"Imported shape valid: {shape.isValid()}")
    print(f"Solids found: {len(solids_sorted)}")
    for i, s in enumerate(solids_sorted[:6]):
        bb = s.BoundingBox()
        print(f"  solid[{i}] vol={safe_volume(s):.3f} bbox=({bb.xlen:.3f},{bb.ylen:.3f},{bb.zlen:.3f})")

    bb = main.BoundingBox()
    print(f"Main bbox: x[{bb.xmin:.3f},{bb.xmax:.3f}] y[{bb.ymin:.3f},{bb.ymax:.3f}] z[{bb.zmin:.3f},{bb.zmax:.3f}]")

    # --- infer thickness axis by smallest bbox dimension ---
    lens = {"X": bb.xlen, "Y": bb.ylen, "Z": bb.zlen}
    thickness_axis = min(lens, key=lens.get)
    axis_min = {"X": bb.xmin, "Y": bb.ymin, "Z": bb.zmin}[thickness_axis]
    axis_max = {"X": bb.xmax, "Y": bb.ymax, "Z": bb.zmax}[thickness_axis]
    axis_mid = 0.5 * (axis_min + axis_max)

    axis_vec = {"X": cq.Vector(1, 0, 0), "Y": cq.Vector(0, 1, 0), "Z": cq.Vector(0, 0, 1)}[thickness_axis]

    print(f"Inferred thickness axis: {thickness_axis} (len={lens[thickness_axis]:.3f})")
    print(f"Axis min={axis_min:.3f} mid={axis_mid:.3f} max={axis_max:.3f}")
    print("Top/Bottom convention used: TOP=axis_max, BOTTOM=axis_min (STEP has no feature history; 'bigger radius side' not reliably detectable).")

    # --- parameters (STEP assumed mm) ---
    offset_mm = 20.0      # 2 cm
    support_thk_mm = 5.0  # 0.5 cm
    top_fillet_mm = 2.0   # 0.2 cm

    # attempt to remove bottom radii by trimming and rebuilding down as sharp walls
    trim_up_mm = 12.0

    # choose canonical plane for the section/sketch (normal = +thickness axis)
    base_plane = {"X": "YZ", "Y": "XZ", "Z": "XY"}[thickness_axis]

    def coord(v: cq.Vector, ax_name: str) -> float:
        return getattr(v, ax_name.lower())

    def make_keep_box_for_above(axis_name: str, keep_from: float, margin: float):
        cx = 0.5 * (bb.xmin + bb.xmax)
        cy = 0.5 * (bb.ymin + bb.ymax)
        cz = 0.5 * (bb.zmin + bb.zmax)

        if axis_name == "X":
            x0, x1 = keep_from, axis_max + margin
            return (
                cq.Workplane("XY")
                .box((x1 - x0), bb.ylen + 2 * margin, bb.zlen + 2 * margin)
                .translate((0.5 * (x0 + x1), cy, cz))
                .val()
            )
        if axis_name == "Y":
            y0, y1 = keep_from, axis_max + margin
            return (
                cq.Workplane("XY")
                .box(bb.xlen + 2 * margin, (y1 - y0), bb.zlen + 2 * margin)
                .translate((cx, 0.5 * (y0 + y1), cz))
                .val()
            )
        # Z
        z0, z1 = keep_from, axis_max + margin
        return (
            cq.Workplane("XY")
            .box(bb.xlen + 2 * margin, bb.ylen + 2 * margin, (z1 - z0))
            .translate((cx, cy, 0.5 * (z0 + z1)))
            .val()
        )

    def section_closed_wires_at(solid, axis_value: float):
        """Return list[(area, wire)] sorted desc for closed wires at a section plane."""
        # workplane normal is +axis for these canonical planes
        wp = cq.Workplane(base_plane).workplane(offset=axis_value).add(solid).section()

        # robust: combine edges into wires
        try:
            edges = wp.edges().vals()
        except Exception:
            edges = []

        wires = []
        if edges:
            try:
                wires = cq.Wire.combine(edges)
            except Exception:
                wires = []

        # sometimes section() already produces wires
        if not wires:
            try:
                wires = list(wp.wires().vals())
            except Exception:
                wires = []

        closed = []
        for w in wires:
            try:
                if not w.isClosed():
                    continue
            except Exception:
                continue
            area = None
            try:
                area = abs(cq.Face.makeFromWires(w).Area())
            except Exception:
                b = w.BoundingBox()
                # bbox area in the section plane
                if thickness_axis == "X":
                    area = float(b.ylen * b.zlen)
                elif thickness_axis == "Y":
                    area = float(b.xlen * b.zlen)
                else:
                    area = float(b.xlen * b.ylen)
            if area and area > 1e-3:
                closed.append((float(area), w))

        closed.sort(key=lambda t: t[0], reverse=True)
        return closed

    thickness_len = axis_max - axis_min
    if thickness_len <= 1e-6:
        raise ValueError("Degenerate thickness axis; cannot proceed")

    # ---------------------------------------------------------------------
    # 1/3) Bottom de-round: trim off bottom blends and rebuild sharp down
    # ---------------------------------------------------------------------
    trim_up = min(trim_up_mm, 0.45 * thickness_len)
    trim_plane = axis_min + trim_up
    margin = max(20.0, 0.05 * max(bb.xlen, bb.ylen, bb.zlen))

    print(f"Bottom de-round attempt: trim_up={trim_up:.3f} at {thickness_axis}={trim_plane:.3f}")

    keep_box = make_keep_box_for_above(thickness_axis, trim_plane, margin)
    main_top = main.intersect(keep_box)

    wires_trim = section_closed_wires_at(main, trim_plane)
    print(f"Section @ trim plane: closed_wires={len(wires_trim)} areas={[round(a,1) for a,_ in wires_trim[:4]]}")

    main_sq = main
    de_round_ok = False
    if len(wires_trim) >= 2:
        outer_w = wires_trim[0][1]
        inner_w = wires_trim[1][1]
        try:
            face = cq.Face.makeFromWires(outer_w, [inner_w])
            # extrude DOWN (toward axis_min): negative distance along plane normal
            rebuild = cq.Workplane(base_plane).workplane(offset=trim_plane).add(face).extrude(-trim_up).val()
            main_sq = cq.Workplane(obj=main_top).union(rebuild).val()
            de_round_ok = True
            print("Bottom de-round applied: rebuilt sharp walls down to bottom plane.")
        except Exception as e:
            print(f"WARNING: bottom de-round rebuild failed: {e}")
            main_sq = main
    else:
        print("WARNING: could not get 2 closed wires at trim plane; skipping bottom de-round.")

    # ---------------------------------------------------------------------
    # 2/3) Add bottom support step: offset inner opening outward by 20mm,
    #       extrude downward 5mm.
    # ---------------------------------------------------------------------
    wires_mid = section_closed_wires_at(main_sq, axis_mid)
    print(f"Section @ mid plane: closed_wires={len(wires_mid)} areas={[round(a,1) for a,_ in wires_mid[:4]]}")
    if len(wires_mid) < 2:
        raise ValueError("Could not derive outer+inner section wires at mid-plane; cannot build support ring")

    outer_mid = wires_mid[0][1]
    inner_mid = wires_mid[1][1]

    # move inner wire from mid to bottom plane
    delta_to_bottom = axis_min - axis_mid
    inner_bottom = inner_mid.translate(axis_vec.multiply(delta_to_bottom))

    def best_offset_wire(wire, dist):
        wpo = cq.Workplane(base_plane).workplane(offset=axis_min).add(wire).toPending().offset2D(dist, kind="arc")
        cands = []
        try:
            ws = list(wpo.wires().vals())
        except Exception:
            ws = []
        for ww in ws:
            try:
                if not ww.isClosed():
                    continue
            except Exception:
                continue
            try:
                a = abs(cq.Face.makeFromWires(ww).Area())
            except Exception:
                b = ww.BoundingBox()
                if thickness_axis == "X":
                    a = b.ylen * b.zlen
                elif thickness_axis == "Y":
                    a = b.xlen * b.zlen
                else:
                    a = b.xlen * b.ylen
            if a and a > 1e-3:
                cands.append((float(a), ww))
        cands.sort(key=lambda t: t[0], reverse=True)
        return cands[0] if cands else (None, None)

    a_pos, w_pos = best_offset_wire(inner_bottom, +offset_mm)
    a_neg, w_neg = best_offset_wire(inner_bottom, -offset_mm)
    print(f"Offset candidates: +{offset_mm}mm area={a_pos} ; -{offset_mm}mm area={a_neg}")

    if w_pos is None and w_neg is None:
        raise ValueError("offset2D failed in both directions for the inner opening wire")

    # choose the offset that creates the bigger enclosed area (should be outward)
    if w_pos is not None and (w_neg is None or (a_pos is not None and a_neg is not None and a_pos >= a_neg)):
        offset_outer = w_pos
        chosen = +offset_mm
    else:
        offset_outer = w_neg
        chosen = -offset_mm
    print(f"Chosen support offset: {chosen}mm")

    try:
        ring_face = cq.Face.makeFromWires(offset_outer, [inner_bottom])
    except Exception as e:
        raise ValueError(f"Failed to make ring face from offset+inner wires: {e}")

    support = cq.Workplane(base_plane).workplane(offset=axis_min).add(ring_face).extrude(-support_thk_mm).val()

    combined = cq.Workplane(obj=main_sq).union(support).val()

    # ---------------------------------------------------------------------
    # 3/3) Apply ONLY top-side fillet (2mm) at the step shoulder edges
    #      (plane at axis_min), excluding the OUTERMOST perimeter edges.
    # ---------------------------------------------------------------------
    # build an outer-bounds normalization from the outer section wire bbox
    outer_bb = outer_mid.BoundingBox()
    if thickness_axis == "X":
        half1 = max(1e-6, 0.5 * outer_bb.ylen)
        half2 = max(1e-6, 0.5 * outer_bb.zlen)
        c1 = 0.5 * (outer_bb.ymin + outer_bb.ymax)
        c2 = 0.5 * (outer_bb.zmin + outer_bb.zmax)
        def normpos(p):
            return max(abs(p.y - c1) / half1, abs(p.z - c2) / half2)
    elif thickness_axis == "Y":
        half1 = max(1e-6, 0.5 * outer_bb.xlen)
        half2 = max(1e-6, 0.5 * outer_bb.zlen)
        c1 = 0.5 * (outer_bb.xmin + outer_bb.xmax)
        c2 = 0.5 * (outer_bb.zmin + outer_bb.zmax)
        def normpos(p):
            return max(abs(p.x - c1) / half1, abs(p.z - c2) / half2)
    else:
        half1 = max(1e-6, 0.5 * outer_bb.xlen)
        half2 = max(1e-6, 0.5 * outer_bb.ylen)
        c1 = 0.5 * (outer_bb.xmin + outer_bb.xmax)
        c2 = 0.5 * (outer_bb.ymin + outer_bb.ymax)
        def normpos(p):
            return max(abs(p.x - c1) / half1, abs(p.y - c2) / half2)

    tol = max(0.08, 0.1 * top_fillet_mm)

    def edge_on_plane_and_not_outermost(e):
        # edges whose vertices lie on the step shoulder plane (axis_min)
        try:
            verts = list(e.Vertices())
        except Exception:
            return False
        if not verts:
            return False
        for v in verts:
            p = v.Center()
            if abs(coord(p, thickness_axis) - axis_min) > tol:
                return False
        # exclude edges near the global outer perimeter by normalized position
        try:
            pc = e.Center()
        except Exception:
            pc = verts[0].Center()
        return normpos(pc) < 0.88

    try:
        combined_f = cq.Workplane(obj=combined).edges().filter(edge_on_plane_and_not_outermost).fillet(top_fillet_mm).val()
        print("Applied top-side step fillet (2mm) on shoulder edges; bottom edges left sharp.")
    except Exception as e:
        combined_f = combined
        print(f"WARNING: Fillet operation failed; returning without shoulder fillet. Error: {e}")

    if others:
        comp = cq.Compound.makeCompound([combined_f] + others)
        return cq.Workplane(obj=comp)

    return cq.Workplane(obj=combined_f)
