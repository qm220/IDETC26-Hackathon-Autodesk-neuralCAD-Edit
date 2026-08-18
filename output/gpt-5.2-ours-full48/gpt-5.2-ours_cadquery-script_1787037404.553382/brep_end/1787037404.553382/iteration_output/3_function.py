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

    bb = shape.BoundingBox()
    print(f"Imported shape valid: {shape.isValid()}")
    print(f"BBox: x[{bb.xmin:.3f},{bb.xmax:.3f}] y[{bb.ymin:.3f},{bb.ymax:.3f}] z[{bb.zmin:.3f},{bb.zmax:.3f}]")
    print(f"Approx size: X={bb.xlen:.3f} Y={bb.ylen:.3f} Z={bb.zlen:.3f}")

    # --- Determine thickness axis as smallest bbox dimension ---
    lens = {"X": bb.xlen, "Y": bb.ylen, "Z": bb.zlen}
    thickness_axis = min(lens, key=lens.get)
    axis_vecs = {"X": cq.Vector(1, 0, 0), "Y": cq.Vector(0, 1, 0), "Z": cq.Vector(0, 0, 1)}
    ax = axis_vecs[thickness_axis]

    axis_min = {"X": bb.xmin, "Y": bb.ymin, "Z": bb.zmin}[thickness_axis]
    axis_max = {"X": bb.xmax, "Y": bb.ymax, "Z": bb.zmax}[thickness_axis]

    # Convention used for this edit:
    # TOP = max along thickness axis, BOTTOM = min along thickness axis
    bottom_coord = axis_min
    top_coord = axis_max
    print(f"Inferred thickness axis: {thickness_axis} (len={lens[thickness_axis]:.3f})")
    print(f"Bottom coord along {thickness_axis}: {bottom_coord:.3f}; Top coord: {top_coord:.3f}")

    # --- Parameters (assume STEP units are mm) ---
    offset_mm = 20.0      # 2 cm
    support_thk_mm = 5.0  # 0.5 cm
    top_fillet_mm = 2.0   # 0.2 cm

    def coord_of(pt, axis_name):
        return getattr(pt, axis_name.lower())

    def wire_area(w):
        try:
            return abs(cq.Face.makeFromWires(w).Area())
        except Exception:
            return None

    def make_plane_at(axis_name, axis_value, normal_vec: cq.Vector):
        cx = 0.5 * (bb.xmin + bb.xmax)
        cy = 0.5 * (bb.ymin + bb.ymax)
        cz = 0.5 * (bb.zmin + bb.zmax)
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

    # --- Find a section plane that yields BOTH outer and inner loops (>=2 wires) ---
    # The last iteration failed because a bottom-near section only produced 1 wire.
    # Scan a few section locations across thickness to robustly find the inner opening.
    tlen = lens[thickness_axis]
    margin = 1.0  # mm
    lo = axis_min + margin
    hi = axis_max - margin
    if hi <= lo:
        raise ValueError("Model thickness too small to section robustly")

    sample_ts = [0.2, 0.35, 0.5, 0.65, 0.8]
    sample_coords = [lo + (hi - lo) * t for t in sample_ts]

    chosen_wire = None
    chosen_section_coord = None

    for c in sample_coords:
        plane_section = make_plane_at(thickness_axis, c, ax)
        sec = cq.Workplane(plane_section).add(shape).section()
        try:
            sec = sec.consolidateWires()
        except Exception:
            pass
        wires = list(sec.wires().vals())

        areas = []
        for w in wires:
            a = wire_area(w)
            if a is not None and a > 1e-6:
                areas.append(a)
        areas_sorted = sorted(areas)
        print(f"Section @ {thickness_axis}={c:.3f}: wires={len(wires)} usable_areas={['%.1f'%a for a in areas_sorted[:6]]}{'...' if len(areas_sorted)>6 else ''}")

        if len(wires) >= 2:
            # pick the smallest-area usable wire as the inner opening loop
            scored = []
            for w in wires:
                a = wire_area(w)
                if a is None or a <= 1e-6:
                    continue
                scored.append((a, w))
            if len(scored) >= 2:
                scored.sort(key=lambda t: t[0])
                chosen_wire = scored[0][1]
                chosen_section_coord = c
                print(f"Chose inner wire from section @ {thickness_axis}={c:.3f} (area={scored[0][0]:.3f})")
                break

    if chosen_wire is None:
        raise ValueError("Could not find a section plane producing both inner+outer loops; cannot derive inner opening")

    # Move the inner wire from the section plane to the bottom reference plane
    delta_to_bottom = bottom_coord - chosen_section_coord
    inner_wire = chosen_wire.translate(ax.multiply(delta_to_bottom))

    # Support sketch plane at bottom, outward normal pointing out of part (toward bottom)
    outward = ax.multiply(-1)  # bottom-out
    plane_support = make_plane_at(thickness_axis, bottom_coord, outward)

    # --- Offset helper (CadQuery version-tolerant retrieval of wires) ---
    def get_wires_from_wp(wp_obj):
        # CadQuery internals differ across versions; try several access paths.
        ws = []
        try:
            ws = list(getattr(wp_obj.ctx, "pendingWires", []))
        except Exception:
            ws = []
        if ws:
            return ws
        try:
            ws = list(wp_obj.wires().vals())
            if ws:
                return ws
        except Exception:
            pass
        try:
            ws = [o for o in getattr(wp_obj, "objects", []) if isinstance(o, cq.Wire)]
            if ws:
                return ws
        except Exception:
            pass
        return []

    def offset_wire(dist, kind):
        wpo = cq.Workplane(plane_support).add(inner_wire).toPending().offset2D(dist, kind=kind)
        ws = get_wires_from_wp(wpo)
        if not ws:
            raise ValueError(f"offset2D produced no wires (dist={dist}, kind={kind})")
        # choose the largest area result as the main offset loop
        best = None
        best_a = -1.0
        for w in ws:
            a = wire_area(w)
            if a is None:
                continue
            if a > best_a:
                best_a = a
                best = w
        return best if best is not None else ws[0]

    base_a = wire_area(inner_wire) or 0.0

    # Try offset in both directions; pick outward = area increase
    last_err = None
    ow_pos = ow_neg = None
    for kind in ("arc", "intersection"):
        try:
            ow_pos = offset_wire(+offset_mm, kind)
            ow_neg = offset_wire(-offset_mm, kind)
            break
        except Exception as e:
            last_err = e
            ow_pos = ow_neg = None

    if ow_pos is None or ow_neg is None:
        raise ValueError(f"Offset failed in all modes: {last_err}")

    a_pos = wire_area(ow_pos) or 0.0
    a_neg = wire_area(ow_neg) or 0.0

    if a_pos >= a_neg:
        offset_outer = ow_pos
        chosen = "+"
        chosen_a = a_pos
    else:
        offset_outer = ow_neg
        chosen = "-"
        chosen_a = a_neg

    print(f"Inner area={base_a:.3f}; offset(+)={a_pos:.3f}, offset(-)={a_neg:.3f} => chosen {chosen} (area={chosen_a:.3f})")

    # --- Create annular face and extrude outward from bottom by 5mm (support thickness) ---
    ring_face = cq.Face.makeFromWires(offset_outer, [inner_wire])
    support = cq.Workplane(plane_support).add(ring_face).extrude(support_thk_mm)  # along plane_support normal (= outward)

    # --- Fillet only TOP edges of support (at the shoulder), leave bottom sharp ---
    sup_shape = support.val()
    sup_bb = sup_shape.BoundingBox()
    sup_top_coord = {"X": sup_bb.xmax, "Y": sup_bb.ymax, "Z": sup_bb.zmax}[thickness_axis]  # along +axis
    sup_bot_coord = {"X": sup_bb.xmin, "Y": sup_bb.ymin, "Z": sup_bb.zmin}[thickness_axis]  # along -axis
    # For support extruded outward from bottom (bottom=min), support spans [bottom-support_thk, bottom]
    print(f"Support bbox along {thickness_axis}: [{sup_bot_coord:.3f},{sup_top_coord:.3f}] (expect top~{bottom_coord:.3f})")

    tol = 0.05  # mm

    def edge_vertices_all_at(e, axis_name, target):
        try:
            for v in e.Vertices():
                if abs(coord_of(v.Center(), axis_name) - target) > tol:
                    return False
            return True
        except Exception:
            return False

    top_edges_cnt = sum(1 for e in sup_shape.Edges() if edge_vertices_all_at(e, thickness_axis, sup_top_coord))
    bot_edges_cnt = sum(1 for e in sup_shape.Edges() if edge_vertices_all_at(e, thickness_axis, sup_bot_coord))
    print(f"Support candidate edges: top={top_edges_cnt}, bottom={bot_edges_cnt}")

    if top_edges_cnt > 0:
        support = (
            cq.Workplane(obj=sup_shape)
            .edges()
            .filter(lambda e: edge_vertices_all_at(e, thickness_axis, sup_top_coord))
            .fillet(top_fillet_mm)
        )

    # --- Union with original body ---
    result = cq.Workplane(obj=shape).union(support)
    return result
