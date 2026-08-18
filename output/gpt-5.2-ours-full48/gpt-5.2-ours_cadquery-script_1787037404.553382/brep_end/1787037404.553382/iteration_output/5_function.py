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
        # Sometimes STEP imports as a single Solid already
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

    # Convention for this edit:
    # TOP = max along thickness axis, BOTTOM = min along thickness axis
    print(f"Inferred thickness axis (main solid): {thickness_axis} (len={lens[thickness_axis]:.3f})")
    print(f"Axis min={axis_min:.3f} mid={axis_mid:.3f} max={axis_max:.3f}")

    # --- Parameters (assume STEP units are mm) ---
    offset_mm = 20.0      # 2 cm outward offset from inner wall
    support_thk_mm = 5.0  # 0.5 cm support thickness
    top_fillet_mm = 2.0   # 0.2 cm fillet on TOP edges of support only

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

    # --- Find a suitable BOTTOM planar reference on the MAIN solid (broad face) ---
    # We look for faces with near-zero span along the thickness axis (i.e., normals ~ +/-ax)
    faces = list(main.Faces())
    tol_flat = max(0.05, lens[thickness_axis] * 1e-3)  # e.g. ~0.17mm for 168mm thickness

    planar_like = []
    for f in faces:
        fbb = f.BoundingBox()
        fmin, fmax = minmax_along_bb(fbb, thickness_axis)
        span = abs(fmax - fmin)
        if span <= tol_flat:
            try:
                a = float(f.Area())
            except Exception:
                a = 0.0
            # use face center coordinate along thickness axis
            try:
                c = f.Center()
                ccoord = coord_of(c, thickness_axis)
            except Exception:
                ccoord = 0.5 * (fmin + fmax)
            planar_like.append((ccoord, -a, f))

    if planar_like:
        planar_like.sort(key=lambda t: (t[0], t[1]))  # lowest coord first, then largest area
        bottom_face = planar_like[0][2]
        bottom_plane_coord = planar_like[0][0]
        print(f"Bottom planar-like face chosen at {thickness_axis}={bottom_plane_coord:.3f} (tol_flat={tol_flat:.3f})")
    else:
        bottom_face = None
        bottom_plane_coord = axis_min
        print(f"WARNING: No planar-like bottom faces found; falling back to axis_min {thickness_axis}={bottom_plane_coord:.3f}")

    # Support plane: located at the chosen bottom plane, normal points outward (toward BOTTOM)
    plane_support_top = make_plane_at(thickness_axis, bottom_plane_coord, ax.multiply(-1), bb)

    # --- Derive inner opening wire from a mid-thickness section of MAIN solid ---
    plane_section = make_plane_at(thickness_axis, axis_mid, ax, bb)
    sec = cq.Workplane(plane_section).add(main).section()
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
    print(f"Section @ {thickness_axis}={axis_mid:.3f}: usable_wires={len(scored)} top_areas={[round(t[0],1) for t in scored[:6]]}")

    if len(scored) < 2:
        raise ValueError("Could not derive inner opening: mid-thickness section on main solid produced <2 usable wires.")

    outer_wire = scored[0][1]
    inner_wire = scored[1][1]

    # Translate inner wire to the support top plane (bottom_plane_coord)
    delta = (bottom_plane_coord - axis_mid)
    inner_wire = inner_wire.translate(ax.multiply(delta))

    base_a = wire_area(inner_wire) or 0.0
    print(f"Inner opening wire area (at support top plane): {base_a:.3f}")

    # --- Offset inner wire outward by 20mm (choose direction that increases area) ---
    def offset_wire(w, dist, kind="arc"):
        # Try Workplane.offset2D for robustness
        wpo = cq.Workplane(plane_support_top).add(w).toPending().offset2D(dist, kind=kind)
        ws = []
        try:
            ws = list(wpo.wires().vals())
        except Exception:
            ws = []
        if not ws:
            # fallback direct
            try:
                res = w.offset2D(dist, kind=kind)
                ws = [res] if isinstance(res, cq.Wire) else list(res)
            except Exception:
                ws = []
        # choose largest area
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

    w_pos, a_pos = offset_wire(inner_wire, +offset_mm, kind="arc")
    w_neg, a_neg = offset_wire(inner_wire, -offset_mm, kind="arc")
    print(f"Offset test: +{offset_mm:.3f}mm area={a_pos:.3f} ; -{offset_mm:.3f}mm area={a_neg:.3f}")

    if w_pos is None and w_neg is None:
        raise ValueError("Failed to offset inner opening wire in either direction.")

    # outward offset should increase area relative to base
    candidates = []
    if w_pos is not None:
        candidates.append((a_pos, +offset_mm, w_pos))
    if w_neg is not None:
        candidates.append((a_neg, -offset_mm, w_neg))
    candidates.sort(key=lambda t: t[0], reverse=True)

    offset_outer = candidates[0][2]
    chosen_dist = candidates[0][1]
    chosen_area = candidates[0][0]
    print(f"Chosen offset: dist={chosen_dist:.3f}mm area={chosen_area:.3f}")

    if chosen_area <= base_a + 1e-6:
        print("WARNING: Chosen offset did not increase area; support may not be offset outward as intended.")

    # --- Build support annulus and extrude outward from bottom by 5mm ---
    ring_face = cq.Face.makeFromWires(offset_outer, [inner_wire])
    support = cq.Workplane(plane_support_top).add(ring_face).extrude(support_thk_mm)  # along -ax

    # --- Fillet ONLY the TOP edges of the support (at the support top plane), leave bottom sharp ---
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

    top_edges = [e for e in sup_shape.Edges() if edge_on_plane(e, thickness_axis, bottom_plane_coord)]
    print(f"Support top-plane edges selected for fillet: {len(top_edges)}")

    if top_edges:
        support = cq.Workplane(obj=sup_shape).edges().filter(lambda e: e in top_edges).fillet(top_fillet_mm)
    else:
        print("WARNING: No support top edges found to fillet; skipping fillet.")

    # --- Union support with MAIN solid ---
    edited_main = cq.Workplane(obj=main).union(support).val()

    # --- Recombine with any other solids (keep them unchanged) ---
    if others:
        comp = cq.Compound.makeCompound([edited_main] + others)
        result = cq.Workplane(obj=comp)
    else:
        result = cq.Workplane(obj=edited_main)

    return result
