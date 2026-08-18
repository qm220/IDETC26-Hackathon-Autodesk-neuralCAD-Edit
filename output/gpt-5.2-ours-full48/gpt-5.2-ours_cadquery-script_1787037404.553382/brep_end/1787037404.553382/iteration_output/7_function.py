def my_cad_function(args):
    import cadquery as cq
    import os

    if "input_file" not in args:
        raise ValueError("Expected args['input_file']")

    input_file = os.path.expanduser(args["input_file"])
    wp = cq.importers.importStep(input_file)
    shape = wp.val() if hasattr(wp, "val") else wp
    if shape is None:
        raise ValueError("Failed to import STEP")

    solids = list(shape.Solids())
    if not solids:
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

    print(f"Inferred thickness axis (main solid): {thickness_axis} (len={lens[thickness_axis]:.3f})")
    print(f"Axis min={axis_min:.3f} mid={axis_mid:.3f} max={axis_max:.3f}")
    print("Top/Bottom convention: TOP = axis_max, BOTTOM = axis_min (STEP-only; 'bigger radius side' not reliably detectable).")

    # --- Parameters (STEP assumed mm) ---
    offset_mm = 20.0       # 2cm
    support_thk_mm = 5.0   # 0.5cm
    top_fillet_mm = 2.0    # 0.2cm

    # Bottom sharp requirement: remove bottom radii by trimming up and rebuilding straight down
    trim_up_mm = 12.0      # must be >= (10mm bottom rounds) + margin
    interface_eps = 1.0    # section slightly above bottom for robust inner profile

    def coord_of(v: cq.Vector, axis_name: str) -> float:
        return getattr(v, axis_name.lower())

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

    def is_wire_closed(w):
        try:
            return bool(w.isClosed())
        except Exception:
            try:
                return bool(w.Wrapped.IsClosed())
            except Exception:
                return False

    def wire_bbox_score_in_section_plane(w, axis_name: str):
        # score by bbox area in the two non-thickness axes
        b = w.BoundingBox()
        if axis_name == "X":
            return float(b.ylen * b.zlen)
        if axis_name == "Y":
            return float(b.xlen * b.zlen)
        return float(b.xlen * b.ylen)

    def section_closed_wires(target_shape, axis_value, normal_vec):
        pl = make_plane_at(thickness_axis, axis_value, normal_vec, bb)
        sec = cq.Workplane(pl).add(target_shape).section()
        try:
            sec = sec.consolidateWires()
        except Exception:
            pass
        wires = list(sec.wires().vals())
        closed = [w for w in wires if is_wire_closed(w)]
        scored = []
        for w in closed:
            s = wire_bbox_score_in_section_plane(w, thickness_axis)
            if s > 1e-3:
                scored.append((s, w))
        scored.sort(key=lambda t: t[0], reverse=True)
        return pl, scored

    def offset_wire_on_plane(pl, w, dist, kind="arc"):
        wpo = cq.Workplane(pl).add(w).toPending().offset2D(dist, kind=kind)
        ws = []
        try:
            ws = list(wpo.wires().vals())
        except Exception:
            ws = []
        # pick the offset with biggest bbox score
        best = None
        best_s = -1.0
        for ww in ws:
            if not is_wire_closed(ww):
                continue
            s = wire_bbox_score_in_section_plane(ww, thickness_axis)
            if s > best_s:
                best_s = s
                best = ww
        return best, best_s

    thickness_len = axis_max - axis_min
    if thickness_len <= 1e-6:
        raise ValueError("Degenerate thickness; cannot determine top/bottom.")

    trim_up = min(trim_up_mm, 0.45 * thickness_len)
    trim_plane_val = axis_min + trim_up
    print(f"Bottom de-round: trim_up={trim_up:.3f}mm at {thickness_axis}={trim_plane_val:.3f}")

    # Keep portion above trim plane by intersecting a big box
    margin = max(10.0, 0.02 * max(bb.xlen, bb.ylen, bb.zlen))
    cx = 0.5 * (bb.xmin + bb.xmax)
    cy = 0.5 * (bb.ymin + bb.ymax)
    cz = 0.5 * (bb.zmin + bb.zmax)

    if thickness_axis == "X":
        x0, x1 = trim_plane_val, axis_max + margin
        keeper = cq.Workplane("XY").box((x1 - x0), bb.ylen + 2 * margin, bb.zlen + 2 * margin).translate((0.5 * (x0 + x1), cy, cz))
    elif thickness_axis == "Y":
        y0, y1 = trim_plane_val, axis_max + margin
        keeper = cq.Workplane("XY").box(bb.xlen + 2 * margin, (y1 - y0), bb.zlen + 2 * margin).translate((cx, 0.5 * (y0 + y1), cz))
    else:
        z0, z1 = trim_plane_val, axis_max + margin
        keeper = cq.Workplane("XY").box(bb.xlen + 2 * margin, bb.ylen + 2 * margin, (z1 - z0)).translate((cx, cy, 0.5 * (z0 + z1)))

    main_top = main.intersect(keeper.val())

    # Section at trim plane to get outer+inner loops for rebuild
    pl_trim, scored_trim = section_closed_wires(main_top, trim_plane_val, ax)
    print(f"Section @ trim plane: closed_wires={len(scored_trim)} scores={[round(t[0],1) for t in scored_trim[:6]]}")

    if len(scored_trim) < 2:
        print("WARNING: Could not extract outer+inner closed wires at trim plane; bottom radii may remain.")
        main_sq = main
    else:
        outer_w = scored_trim[0][1]
        inner_w = scored_trim[1][1]
        try:
            rebuild_face = cq.Face.makeFromWires(outer_w, [inner_w])
            # extrude DOWN to bottom (sharp) from trim plane
            pl_trim_down = make_plane_at(thickness_axis, trim_plane_val, ax.multiply(-1), bb)
            slab = cq.Workplane(pl_trim_down).add(rebuild_face).extrude(trim_up)
            main_sq = cq.Workplane(obj=main_top).union(slab).val()
            print(f"Bottom de-round applied: rebuilt straight wall down by {trim_up:.3f}mm")
        except Exception as e:
            print(f"WARNING: Bottom de-round rebuild failed ({e}); keeping original main.")
            main_sq = main

    # --- Build the bottom support step: offset inner wall outward by 20mm, extrude 5mm downward ---
    # Take section slightly above bottom to capture inner wall profile robustly
    support_profile_y = axis_min + min(interface_eps, 0.1 * thickness_len)
    pl_prof, scored_prof = section_closed_wires(main_sq, support_profile_y, ax)
    print(f"Section @ support profile plane ({thickness_axis}={support_profile_y:.3f}): closed_wires={len(scored_prof)}")

    if len(scored_prof) < 2:
        raise ValueError("Could not derive inner opening wire near bottom; need >=2 closed wires in section.")

    inner_wire = scored_prof[1][1]
    # move inner wire down to axis_min (support top plane)
    inner_wire = inner_wire.translate(ax.multiply(axis_min - support_profile_y))

    plane_support_top = make_plane_at(thickness_axis, axis_min, ax.multiply(-1), bb)  # normal points DOWN

    w_pos, s_pos = offset_wire_on_plane(plane_support_top, inner_wire, +offset_mm, kind="arc")
    w_neg, s_neg = offset_wire_on_plane(plane_support_top, inner_wire, -offset_mm, kind="arc")
    print(f"Offset test (support): +{offset_mm:.3f}mm score={s_pos:.3f} ; -{offset_mm:.3f}mm score={s_neg:.3f}")

    candidates = []
    if w_pos is not None:
        candidates.append((s_pos, +offset_mm, w_pos))
    if w_neg is not None:
        candidates.append((s_neg, -offset_mm, w_neg))
    if not candidates:
        raise ValueError("Failed to offset inner opening wire for support ring.")
    candidates.sort(key=lambda t: t[0], reverse=True)
    offset_outer = candidates[0][2]
    chosen_dist = candidates[0][1]
    print(f"Chosen support offset: dist={chosen_dist:.3f}mm")

    ring_face = cq.Face.makeFromWires(offset_outer, [inner_wire])
    support = cq.Workplane(plane_support_top).add(ring_face).extrude(support_thk_mm)  # down

    # --- Fillet ONLY the TOP shoulder edges of the support (at axis_min), keep bottom sharp ---
    sup_shape = support.val()
    tol = max(0.05, top_fillet_mm * 0.1)

    def edge_all_vertices_on_value(e, axis_name, target):
        try:
            for v in e.Vertices():
                if abs(coord_of(v.Center(), axis_name) - target) > tol:
                    return False
            return True
        except Exception:
            return False

    support = cq.Workplane(obj=sup_shape).edges().filter(lambda e: edge_all_vertices_on_value(e, thickness_axis, axis_min)).fillet(top_fillet_mm)

    # Union edited main + support
    edited_main = cq.Workplane(obj=main_sq).union(support).val()

    if others:
        comp = cq.Compound.makeCompound([edited_main] + others)
        return cq.Workplane(obj=comp)
    return cq.Workplane(obj=edited_main)
