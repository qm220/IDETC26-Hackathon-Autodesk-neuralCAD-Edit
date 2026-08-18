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

    # --- Determine thickness axis as the smallest bbox dimension ---
    lens = {"X": bb.xlen, "Y": bb.ylen, "Z": bb.zlen}
    thickness_axis = min(lens, key=lens.get)
    axis_vecs = {"X": cq.Vector(1, 0, 0), "Y": cq.Vector(0, 1, 0), "Z": cq.Vector(0, 0, 1)}
    ax = axis_vecs[thickness_axis]

    axis_min = {"X": bb.xmin, "Y": bb.ymin, "Z": bb.zmin}[thickness_axis]
    axis_max = {"X": bb.xmax, "Y": bb.ymax, "Z": bb.zmax}[thickness_axis]

    # Convention for this edit:
    # TOP = max along thickness axis, BOTTOM = min along thickness axis
    bottom_coord = axis_min
    top_coord = axis_max
    print(f"Inferred thickness axis: {thickness_axis} (len={lens[thickness_axis]:.3f})")
    print(f"Bottom coord along {thickness_axis}: {bottom_coord:.3f}; Top coord: {top_coord:.3f}")

    # --- Parameters (assume STEP units are mm) ---
    offset_mm = 20.0      # 2 cm
    support_thk_mm = 5.0  # 0.5 cm
    top_fillet_mm = 2.0   # 0.2 cm

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

    def wire_length(w):
        try:
            return w.Length()
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

    # --- Try to get inner opening wire from the bottom planar face (most robust) ---
    tol_plane = max(0.05, lens[thickness_axis] * 1e-4)  # adaptive-ish
    faces = list(shape.Faces())
    bottom_planar_candidates = []
    for f in faces:
        fbb = f.BoundingBox()
        fmin, fmax = minmax_along_bb(fbb, thickness_axis)
        # face lies essentially on the bottom plane if both min and max are near bottom_coord
        if abs(fmin - bottom_coord) < tol_plane and abs(fmax - bottom_coord) < tol_plane:
            try:
                a = f.Area()
            except Exception:
                a = 0.0
            bottom_planar_candidates.append((a, f))

    print(f"Bottom planar face candidates near {thickness_axis}={bottom_coord:.3f}: {len(bottom_planar_candidates)}")

    inner_wire = None
    plane_support = make_plane_at(thickness_axis, bottom_coord, ax.multiply(-1))  # outward from bottom

    def unique_wires_by_bb_and_len(wires_in, bb_eps=1e-3, len_eps=1e-3):
        uniq = []
        sigs = []
        for w in wires_in:
            try:
                wbb = w.BoundingBox()
                wl = wire_length(w) or 0.0
                sig = (
                    round(wbb.xmin / bb_eps), round(wbb.xmax / bb_eps),
                    round(wbb.ymin / bb_eps), round(wbb.ymax / bb_eps),
                    round(wbb.zmin / bb_eps), round(wbb.zmax / bb_eps),
                    round(wl / len_eps),
                )
            except Exception:
                sig = None
            if sig is None:
                continue
            if sig in sigs:
                continue
            sigs.append(sig)
            uniq.append(w)
        return uniq

    if bottom_planar_candidates:
        bottom_planar_candidates.sort(key=lambda t: t[0], reverse=True)
        best_face = bottom_planar_candidates[0][1]
        try:
            fwires = list(best_face.Wires())
        except Exception:
            fwires = []
        fwires = unique_wires_by_bb_and_len(fwires)
        scored = []
        for w in fwires:
            a = wire_area(w)
            if a is None or a <= 1e-6:
                continue
            scored.append((a, w))
        scored.sort(key=lambda t: t[0])
        if len(scored) >= 2:
            # outer wire is largest; choose largest "inner" wire among the remainder
            outer = max(scored, key=lambda t: t[0])
            inner_candidates = [t for t in scored if t is not outer]
            inner_wire = max(inner_candidates, key=lambda t: t[0])[1]
            print(f"Bottom face wires: total={len(scored)}; outer_area={outer[0]:.3f}; chosen_inner_area={max(inner_candidates, key=lambda t: t[0])[0]:.3f}")
        else:
            print("Bottom face did not expose >=2 usable wires; will fall back to section-based inner-loop search.")

    # --- Fallback: use a mid-thickness section to find inner wire ---
    if inner_wire is None:
        axis_mid = 0.5 * (axis_min + axis_max)
        plane_section = make_plane_at(thickness_axis, axis_mid, ax)
        sec = cq.Workplane(plane_section).add(shape).section()
        try:
            sec = sec.consolidateWires()
        except Exception:
            pass
        wires = list(sec.wires().vals())
        wires = unique_wires_by_bb_and_len(wires)

        scored = []
        for w in wires:
            a = wire_area(w)
            if a is None or a <= 1e-6:
                continue
            scored.append((a, w))
        scored.sort(key=lambda t: t[0])
        print(f"Section @ {thickness_axis}={axis_mid:.3f}: usable_wires={len(scored)} areas={[round(t[0],1) for t in scored[:8]]}{'...' if len(scored)>8 else ''}")
        if len(scored) < 2:
            raise ValueError("Could not derive inner opening wire (bottom face had <2 wires and section had <2 usable wires).")
        # inner opening is smallest area loop of the section
        inner_wire = scored[0][1]
        # move it to the bottom plane
        delta = bottom_coord - axis_mid
        inner_wire = inner_wire.translate(ax.multiply(delta))
        print("Derived inner opening from section and translated to bottom plane.")

    base_a = wire_area(inner_wire) or 0.0
    print(f"Inner wire area (reference): {base_a:.3f}")

    # --- Offset the inner wire outward by 20mm ---
    def get_wires_from_wp(wp_obj):
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

    def offset_attempt(w, dist, kind):
        # 1) Try Wire.offset2D directly
        try:
            res = w.offset2D(dist, kind=kind)
            if isinstance(res, cq.Wire):
                return [res]
            return list(res)
        except Exception:
            pass
        # 2) Try Workplane.offset2D
        try:
            wpo = cq.Workplane(plane_support).add(w).toPending().offset2D(dist, kind=kind)
            return get_wires_from_wp(wpo)
        except Exception:
            return []

    def best_wire_by_area(wires_list):
        best = None
        best_a = -1.0
        for w in unique_wires_by_bb_and_len(wires_list):
            a = wire_area(w)
            if a is None:
                continue
            if a > best_a:
                best_a = a
                best = w
        return best, best_a

    kinds = ("arc", "intersection", "tangent")
    candidates = []
    last_debug = []
    for kind in kinds:
        for sign in (+1, -1):
            dist = sign * offset_mm
            ws = offset_attempt(inner_wire, dist, kind)
            bw, ba = best_wire_by_area(ws) if ws else (None, -1.0)
            last_debug.append((kind, dist, len(ws), ba))
            if bw is not None and ba > 1e-6:
                candidates.append((ba, kind, dist, bw))

    print("Offset attempts (kind, dist, nWires, bestArea):")
    for kind, dist, nw, ba in last_debug:
        print(f"  {kind:12s} {dist:8.3f} -> wires={nw:2d}, bestArea={ba:10.3f}")

    if not candidates:
        raise ValueError("Failed to offset inner opening wire in any mode/direction; cannot create the 20mm support ring.")

    # Choose the offset that increases area (outward). If multiple, pick the maximum area.
    candidates.sort(key=lambda t: t[0], reverse=True)
    offset_outer = candidates[0][3]
    chosen_area = candidates[0][0]
    chosen_kind = candidates[0][1]
    chosen_dist = candidates[0][2]

    print(f"Chosen offset: kind={chosen_kind}, dist={chosen_dist:.3f}, area={chosen_area:.3f}")

    # --- Build annular face and extrude outward from the bottom by 5mm ---
    ring_face = cq.Face.makeFromWires(offset_outer, [inner_wire])
    support = cq.Workplane(plane_support).add(ring_face).extrude(support_thk_mm)  # along plane_support normal (= out of bottom)

    # --- Fillet only the TOP shoulder edges of the support (NOT the bottom), and prefer OUTER loop only ---
    sup_shape = support.val()
    sup_bb = sup_shape.BoundingBox()
    # Along thickness axis, support top is at bottom_coord, support bottom is below it
    sup_min, sup_max = minmax_along_bb(sup_bb, thickness_axis)
    # The support was extruded outward from the bottom plane, so the TOP of the support is the max along thickness axis
    sup_top_coord = sup_max
    sup_bot_coord = sup_min
    print(f"Support extent along {thickness_axis}: [{sup_bot_coord:.3f}, {sup_top_coord:.3f}] (expect top~{bottom_coord:.3f})")

    tol_edge = max(0.05, support_thk_mm * 0.05)

    def edge_all_vertices_at(e, axis_name, target):
        try:
            for v in e.Vertices():
                if abs(coord_of(v.Center(), axis_name) - target) > tol_edge:
                    return False
            return True
        except Exception:
            return False

    # Collect candidate top edges (lying on the top plane of the support)
    top_edges = [e for e in sup_shape.Edges() if edge_all_vertices_at(e, thickness_axis, sup_top_coord)]
    print(f"Support top-plane edges found: {len(top_edges)}")

    # Separate inner vs outer loop edges by radial distance of edge center from part center (in-plane)
    center = cq.Vector(0.5 * (bb.xmin + bb.xmax), 0.5 * (bb.ymin + bb.ymax), 0.5 * (bb.zmin + bb.zmax))

    def in_plane_dist(p: cq.Vector):
        # distance ignoring thickness axis component
        dx = p.x - center.x
        dy = p.y - center.y
        dz = p.z - center.z
        if thickness_axis == "X":
            return (dy * dy + dz * dz) ** 0.5
        if thickness_axis == "Y":
            return (dx * dx + dz * dz) ** 0.5
        return (dx * dx + dy * dy) ** 0.5

    edge_dists = []
    for e in top_edges:
        try:
            c = e.Center()
        except Exception:
            continue
        edge_dists.append((in_plane_dist(c), e))

    if edge_dists:
        dmin = min(edge_dists, key=lambda t: t[0])[0]
        dmax = max(edge_dists, key=lambda t: t[0])[0]
        thresh = 0.5 * (dmin + dmax)
        print(f"Top-edge in-plane dist range: [{dmin:.3f}, {dmax:.3f}], threshold={thresh:.3f}")
        outer_top_edges = [e for d, e in edge_dists if d >= thresh]
    else:
        outer_top_edges = []

    print(f"Outer-loop top edges selected for fillet: {len(outer_top_edges)}")

    if outer_top_edges:
        support = cq.Workplane(obj=sup_shape).edges().filter(lambda e: e in outer_top_edges).fillet(top_fillet_mm)
    else:
        print("WARNING: Could not isolate outer-loop top edges; skipping fillet to avoid affecting wrong edges.")

    # --- Union with original body ---
    result = cq.Workplane(obj=shape).union(support)
    return result
