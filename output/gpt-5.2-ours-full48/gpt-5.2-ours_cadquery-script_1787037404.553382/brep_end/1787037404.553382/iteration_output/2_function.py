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

    # Convention: bottom=min along thickness axis, top=max
    bottom_coord = axis_min
    top_coord = axis_max
    print(f"Inferred thickness axis: {thickness_axis} (len={lens[thickness_axis]:.3f})")
    print(f"Bottom coord along {thickness_axis}: {bottom_coord:.3f}; Top coord: {top_coord:.3f}")

    def coord_of(pt, axis_name):
        return getattr(pt, axis_name.lower())

    def wire_area(w):
        try:
            return abs(cq.Face.makeFromWires(w).Area())
        except Exception:
            return None

    def make_plane_at(axis_name, axis_value, normal_vec: cq.Vector):
        # Plane passing through model center, positioned at axis_value on the chosen axis
        cx = 0.5 * (bb.xmin + bb.xmax)
        cy = 0.5 * (bb.ymin + bb.ymax)
        cz = 0.5 * (bb.zmin + bb.zmax)
        origin = cq.Vector(cx, cy, cz)
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

    # --- Parameters (model units assumed mm) ---
    offset_mm = 20.0      # 2 cm outward from inner opening
    support_thk_mm = 5.0  # 0.5 cm thickness (downwards)
    top_fillet_mm = 2.0   # 0.2 cm shoulder fillet (top-side only)

    # --- Derive the inner opening loop near the bottom via section (robust vs picking a not-actually-bottom planar face) ---
    # Use a small epsilon inside the part from the bottom to ensure intersection.
    eps = 0.5  # mm
    section_coord = bottom_coord + eps

    plane_section = make_plane_at(thickness_axis, section_coord, ax)
    sec = cq.Workplane(plane_section).add(shape).section()
    wires = list(sec.wires().vals())
    print(f"Section wires at {thickness_axis}={section_coord:.3f}: {len(wires)}")
    if len(wires) < 2:
        raise ValueError("Could not derive inner/outer loops from a bottom-near section; not enough wires")

    wire_scored = []
    for i, w in enumerate(wires):
        a = wire_area(w)
        if a is None:
            continue
        wire_scored.append((a, w))
    if not wire_scored:
        raise ValueError("Section produced wires but none were usable to compute area")

    wire_scored.sort(key=lambda t: t[0])
    inner_wire = wire_scored[0][1]
    print(f"Chosen inner wire from section: area={wire_scored[0][0]:.3f}")

    # Translate inner_wire from section plane to the bottom support plane
    delta = bottom_coord - section_coord
    inner_wire = inner_wire.translate(ax.multiply(delta))

    # Support sketch plane at bottom, with outward normal pointing out of the part (towards bottom)
    outward = ax.multiply(-1)
    plane_support = make_plane_at(thickness_axis, bottom_coord, outward)

    # --- Offset helper ---
    def get_wires_from_wp(wp_obj):
        # Try multiple ways to retrieve resulting wires (CadQuery versions differ)
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
        # Ensure the wire is treated as pending 2D geometry on the plane
        wpo = cq.Workplane(plane_support).add(inner_wire).toPending().offset2D(dist, kind=kind)
        ws = get_wires_from_wp(wpo)
        if not ws:
            raise ValueError(f"offset2D produced no wires (dist={dist}, kind={kind})")
        # pick the largest-area wire (should be the main offset loop)
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

    # Try offset in both directions; pick the one that increases area (outward)
    base_a = wire_area(inner_wire) or 0.0

    def try_offset_both(dist):
        # try arc first, then intersection if arc fails
        for kind in ("arc", "intersection"):
            try:
                ow_p = offset_wire(+dist, kind)
                ow_n = offset_wire(-dist, kind)
                return ow_p, ow_n
            except Exception as e:
                last = e
        raise last

    ow_pos, ow_neg = try_offset_both(offset_mm)
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

    # --- Create annular face and extrude downward (outward from bottom) ---
    ring_face = cq.Face.makeFromWires(offset_outer, [inner_wire])
    support = cq.Workplane(plane_support).add(ring_face).extrude(support_thk_mm)  # along plane_support normal (= outward)

    # --- Fillet ONLY the support's TOP shoulder edges (leave bottom edges sharp/flat) ---
    sup_shape = support.val()
    sup_bb = sup_shape.BoundingBox()
    sup_top = {"X": sup_bb.xmax, "Y": sup_bb.ymax, "Z": sup_bb.zmax}[thickness_axis]
    sup_bot = {"X": sup_bb.xmin, "Y": sup_bb.ymin, "Z": sup_bb.zmin}[thickness_axis]
    print(f"Support bbox along {thickness_axis}: [{sup_bot:.3f},{sup_top:.3f}] (expected top ~ {bottom_coord:.3f})")

    tol = 0.05  # mm

    def edge_vertices_all_at(e, axis_name, target):
        try:
            for v in e.Vertices():
                if abs(coord_of(v.Center(), axis_name) - target) > tol:
                    return False
            return True
        except Exception:
            return False

    top_edges = [e for e in sup_shape.Edges() if edge_vertices_all_at(e, thickness_axis, sup_top)]
    bot_edges = [e for e in sup_shape.Edges() if edge_vertices_all_at(e, thickness_axis, sup_bot)]
    print(f"Support candidate edges: top={len(top_edges)}, bottom={len(bot_edges)}")

    if len(top_edges) > 0:
        support = (
            cq.Workplane(obj=sup_shape)
            .edges()
            .filter(lambda e: edge_vertices_all_at(e, thickness_axis, sup_top))
            .fillet(top_fillet_mm)
        )

    # --- Union with original ---
    result = cq.Workplane(obj=shape).union(support)
    return result
