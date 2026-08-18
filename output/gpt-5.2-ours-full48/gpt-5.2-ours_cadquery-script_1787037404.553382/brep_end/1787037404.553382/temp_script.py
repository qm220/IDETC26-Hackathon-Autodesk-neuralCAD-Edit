def my_cad_function(args):
    import cadquery as cq
    import os, math

    # --- load ---
    if "input_file" not in args:
        raise ValueError("Expected args['input_file']")
    input_file = os.path.expanduser(args["input_file"])
    wp_in = cq.importers.importStep(input_file)
    shape = wp_in.val() if hasattr(wp_in, "val") else wp_in
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

    bb = main.BoundingBox()
    xmid = 0.5 * (bb.xmin + bb.xmax)
    ymid = 0.5 * (bb.ymin + bb.ymax)
    zmid = 0.5 * (bb.zmin + bb.zmax)
    print(f"Main bbox: x[{bb.xmin:.3f},{bb.xmax:.3f}] y[{bb.ymin:.3f},{bb.ymax:.3f}] z[{bb.zmin:.3f},{bb.zmax:.3f}]")

    # --- infer thickness axis by smallest bbox dimension ---
    lens = {"X": bb.xlen, "Y": bb.ylen, "Z": bb.zlen}
    thickness_axis = min(lens, key=lens.get)
    axis_min = {"X": bb.xmin, "Y": bb.ymin, "Z": bb.zmin}[thickness_axis]
    axis_max = {"X": bb.xmax, "Y": bb.ymax, "Z": bb.zmax}[thickness_axis]
    axis_mid = 0.5 * (axis_min + axis_max)

    axis_vec = {"X": cq.Vector(1, 0, 0), "Y": cq.Vector(0, 1, 0), "Z": cq.Vector(0, 0, 1)}[thickness_axis]
    base_plane = {"X": "YZ", "Y": "XZ", "Z": "XY"}[thickness_axis]

    print(f"Inferred thickness axis: {thickness_axis} (len={lens[thickness_axis]:.3f})")
    print(f"Axis min={axis_min:.3f} mid={axis_mid:.3f} max={axis_max:.3f}")
    print("Top/Bottom convention used: TOP=axis_max, BOTTOM=axis_min (STEP has no reliable 'bigger radius side' semantic).")

    # --- parameters (STEP assumed mm) ---
    offset_mm = 20.0      # 2 cm outward from inner opening
    support_thk_mm = 5.0  # 0.5 cm downward
    top_fillet_mm = 2.0   # 0.2 cm on top shoulder only

    def coord(p: cq.Vector, ax: str) -> float:
        return getattr(p, ax.lower())

    # --- find a bottom planar reference (prefer a plane face at the bottom) ---
    bottom_ref = None
    best_y = None
    try:
        faces = list(main.Faces())
    except Exception:
        faces = []

    for f in faces:
        try:
            if str(f.SurfaceType()).upper() != "PLANE":
                continue
        except Exception:
            continue
        try:
            n = f.normalAt()
        except Exception:
            # fallback: skip if can't get normal
            continue

        # want faces whose outward normal points toward -axis_vec (bottom-facing)
        try:
            dn = n.dot(axis_vec.multiply(-1))
        except Exception:
            dn = 0.0

        if dn < 0.90:
            continue

        c = f.Center()
        val = coord(c, thickness_axis)
        if best_y is None or val < best_y:
            best_y = val
            bottom_ref = val

    if bottom_ref is None:
        bottom_ref = axis_min
        print(f"Bottom planar face not found; using bbox axis_min as bottom_ref={bottom_ref:.3f}")
    else:
        print(f"Detected bottom planar reference at {thickness_axis}={bottom_ref:.3f}")

    # --- robust section using OCP (Workplane.section was returning 0 wires previously) ---
    def section_closed_wires_ocp(solid: cq.Shape, axis_value: float):
        from OCP.gp import gp_Pln, gp_Pnt, gp_Dir
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Section

        # plane point at model mid, with axis coordinate set
        px, py, pz = xmid, ymid, zmid
        if thickness_axis == "X":
            px = axis_value
            nd = gp_Dir(1, 0, 0)
        elif thickness_axis == "Y":
            py = axis_value
            nd = gp_Dir(0, 1, 0)
        else:
            pz = axis_value
            nd = gp_Dir(0, 0, 1)

        pln = gp_Pln(gp_Pnt(px, py, pz), nd)
        L = 4.0 * max(bb.xlen, bb.ylen, bb.zlen)
        face = BRepBuilderAPI_MakeFace(pln, -L, L, -L, L).Face()

        sec = BRepAlgoAPI_Section(solid.wrapped, face)
        sec.ComputePCurveOn1(True)
        sec.Approximation(True)
        sec.Build()
        sec_shape = cq.Shape(sec.Shape())

        try:
            edges = list(sec_shape.Edges())
        except Exception:
            edges = []

        wires = []
        if edges:
            try:
                wires = cq.Wire.combine(edges)
            except Exception:
                wires = []

        closed = []
        for w in wires:
            try:
                if not w.isClosed():
                    continue
            except Exception:
                continue
            try:
                a = abs(cq.Face.makeFromWires(w).Area())
            except Exception:
                b = w.BoundingBox()
                # approximate area in section plane
                if thickness_axis == "X":
                    a = b.ylen * b.zlen
                elif thickness_axis == "Y":
                    a = b.xlen * b.zlen
                else:
                    a = b.xlen * b.ylen
            if a and a > 1e-3:
                closed.append((float(a), w))

        closed.sort(key=lambda t: t[0], reverse=True)
        return closed

    eps = 0.5  # section slightly inside the solid

    wires = section_closed_wires_ocp(main, bottom_ref + eps)
    print(f"Section @ {thickness_axis}={bottom_ref + eps:.3f}: closed_wires={len(wires)} areas={[round(a,1) for a,_ in wires[:6]]}")

    # fallback: mid-plane section
    if len(wires) < 2:
        wires = section_closed_wires_ocp(main, axis_mid)
        print(f"Fallback section @ {thickness_axis}={axis_mid:.3f}: closed_wires={len(wires)} areas={[round(a,1) for a,_ in wires[:6]]}")

    if len(wires) < 2:
        raise ValueError("Could not derive outer+inner section wires from OCP section; cannot build support ring")

    outer_w = wires[0][1]
    inner_w = wires[1][1]

    # translate section wires down to bottom_ref plane (we sectioned at bottom_ref+eps)
    # Only do this if we used bottom_ref+eps (detect by comparing centers)
    try:
        inner_c = inner_w.BoundingBox().center
    except Exception:
        inner_c = None

    # We know the first attempt is at bottom_ref+eps; translate by -eps along +axis
    inner_at_bottom = inner_w.translate(axis_vec.multiply(-eps))

    # --- offset inner wire outward by 20mm on bottom_ref plane ---
    def offset_wire_candidates(w: cq.Wire, dist: float):
        wp = cq.Workplane(base_plane).workplane(offset=bottom_ref)
        # put the wire as pending geometry, then offset
        wp = wp.add(w).toPending()
        out = []
        try:
            wp2 = wp.offset2D(dist, kind="arc")
            ws = list(wp2.wires().vals())
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
            out.append((float(a), ww))
        out.sort(key=lambda t: t[0], reverse=True)
        return out

    # compute area of original inner for comparison
    try:
        inner_area = abs(cq.Face.makeFromWires(inner_at_bottom).Area())
    except Exception:
        ib = inner_at_bottom.BoundingBox()
        inner_area = ib.xlen * ib.zlen if thickness_axis == "Y" else (ib.ylen * ib.zlen if thickness_axis == "X" else ib.xlen * ib.ylen)

    cpos = offset_wire_candidates(inner_at_bottom, +offset_mm)
    cneg = offset_wire_candidates(inner_at_bottom, -offset_mm)
    apos = cpos[0][0] if cpos else None
    aneg = cneg[0][0] if cneg else None
    print(f"Inner wire area ~{inner_area:.1f}")
    print(f"Offset candidates: +{offset_mm}mm => {apos} ; -{offset_mm}mm => {aneg}")

    if not cpos and not cneg:
        raise ValueError("offset2D failed in both directions; cannot form support ring")

    # choose the offset that increases area (outward from inner opening)
    chosen_wire = None
    chosen_dist = None
    if cpos and (apos is not None) and apos > inner_area:
        chosen_wire = cpos[0][1]
        chosen_dist = +offset_mm
    elif cneg and (aneg is not None) and aneg > inner_area:
        chosen_wire = cneg[0][1]
        chosen_dist = -offset_mm
    else:
        # fallback: choose larger of the two
        if cpos and (not cneg or (apos is not None and aneg is not None and apos >= aneg)):
            chosen_wire = cpos[0][1]
            chosen_dist = +offset_mm
        else:
            chosen_wire = cneg[0][1]
            chosen_dist = -offset_mm

    print(f"Chosen support offset: {chosen_dist}mm")

    # --- build annular face between inner and offset wire, then extrude downward ---
    try:
        ring_face = cq.Face.makeFromWires(chosen_wire, [inner_at_bottom])
    except Exception as e:
        raise ValueError(f"Failed to make ring face from offset+inner wires: {e}")

    support_solid = (
        cq.Workplane(base_plane)
        .workplane(offset=bottom_ref)
        .add(ring_face)
        .extrude(-support_thk_mm)  # towards bottom (axis decreasing)
        .val()
    )

    combined = cq.Workplane(obj=main).union(support_solid).val()

    # --- apply ONLY top-side fillet (2mm) on shoulder edge(s) at bottom_ref ---
    # Select edges at y=bottom_ref (or axis) and near the OFFSET boundary (not inner boundary), and not on bottom plane.
    inner_bb = inner_at_bottom.BoundingBox()
    off_bb = chosen_wire.BoundingBox()

    # Use section-plane coordinates (two axes orthogonal to thickness axis)
    if thickness_axis == "Y":
        c1 = 0.5 * (off_bb.xmin + off_bb.xmax)
        c2 = 0.5 * (off_bb.zmin + off_bb.zmax)
        ih1 = max(1e-6, 0.5 * inner_bb.xlen)
        ih2 = max(1e-6, 0.5 * inner_bb.zlen)
        oh1 = max(1e-6, 0.5 * off_bb.xlen)
        oh2 = max(1e-6, 0.5 * off_bb.zlen)
        def di(p):
            return max(abs(p.x - c1) / ih1, abs(p.z - c2) / ih2)
        def do(p):
            return max(abs(p.x - c1) / oh1, abs(p.z - c2) / oh2)
    elif thickness_axis == "X":
        c1 = 0.5 * (off_bb.ymin + off_bb.ymax)
        c2 = 0.5 * (off_bb.zmin + off_bb.zmax)
        ih1 = max(1e-6, 0.5 * inner_bb.ylen)
        ih2 = max(1e-6, 0.5 * inner_bb.zlen)
        oh1 = max(1e-6, 0.5 * off_bb.ylen)
        oh2 = max(1e-6, 0.5 * off_bb.zlen)
        def di(p):
            return max(abs(p.y - c1) / ih1, abs(p.z - c2) / ih2)
        def do(p):
            return max(abs(p.y - c1) / oh1, abs(p.z - c2) / oh2)
    else:  # Z
        c1 = 0.5 * (off_bb.xmin + off_bb.xmax)
        c2 = 0.5 * (off_bb.ymin + off_bb.ymax)
        ih1 = max(1e-6, 0.5 * inner_bb.xlen)
        ih2 = max(1e-6, 0.5 * inner_bb.ylen)
        oh1 = max(1e-6, 0.5 * off_bb.xlen)
        oh2 = max(1e-6, 0.5 * off_bb.ylen)
        def di(p):
            return max(abs(p.x - c1) / ih1, abs(p.y - c2) / ih2)
        def do(p):
            return max(abs(p.x - c1) / oh1, abs(p.y - c2) / oh2)

    tol = max(0.10, 0.15 * top_fillet_mm)

    def is_top_shoulder_edge(e):
        # edge vertices should lie on the shoulder plane at bottom_ref (top of support)
        try:
            verts = list(e.Vertices())
        except Exception:
            return False
        if not verts:
            return False
        for v in verts:
            p = v.Center()
            if abs(coord(p, thickness_axis) - bottom_ref) > tol:
                return False

        # choose edges near the OUTER boundary of the added ring (offset boundary)
        try:
            pc = e.Center()
        except Exception:
            pc = verts[0].Center()

        # Do near-offset boundary: do(pc) ~= 1, and NOT near inner boundary: di(pc) should be > ~1
        return (do(pc) > 0.92) and (di(pc) > 1.05)

    try:
        combined_f = (
            cq.Workplane(obj=combined)
            .edges()
            .filter(is_top_shoulder_edge)
            .fillet(top_fillet_mm)
            .val()
        )
        print("Applied 2mm fillet on top shoulder of the new support step; bottom edges left sharp (no bottom fillets added).")
    except Exception as e:
        combined_f = combined
        print(f"WARNING: shoulder fillet failed; returning without it. Error: {e}")

    if others:
        comp = cq.Compound.makeCompound([combined_f] + others)
        return cq.Workplane(obj=comp)

    return cq.Workplane(obj=combined_f)
