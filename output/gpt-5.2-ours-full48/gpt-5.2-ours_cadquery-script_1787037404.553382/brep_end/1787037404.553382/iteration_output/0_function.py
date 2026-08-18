def my_cad_function(args):
    import cadquery as cq
    import os

    # --- Load input STEP ---
    if "input_file" not in args:
        raise ValueError("Expected args['input_file'] for edit task")
    input_file = os.path.expanduser(args["input_file"])
    model_wp = cq.importers.importStep(input_file)
    base_shape = model_wp.val() if hasattr(model_wp, "val") else model_wp

    if base_shape is None:
        raise ValueError("Failed to import STEP shape")

    # --- Debug: overall bbox ---
    bb = base_shape.BoundingBox()
    print(f"Imported shape valid: {base_shape.isValid()}")
    print(f"BBox: x[{bb.xmin:.3f},{bb.xmax:.3f}] y[{bb.ymin:.3f},{bb.ymax:.3f}] z[{bb.zmin:.3f},{bb.zmax:.3f}]")
    print(f"Approx size: X={bb.xlen:.3f} Y={bb.ylen:.3f} Z={bb.zlen:.3f}")

    # --- Find bottom reference planar face (normal ~ -Z, lowest center.z) ---
    faces = list(base_shape.Faces())
    print(f"Face count: {len(faces)}")

    bottom_candidates = []
    for f in faces:
        try:
            if getattr(f, "geomType", lambda: None)() != "PLANE":
                continue
            n = f.normalAt()
            # outward normal of bottom face should be close to -Z for a typical solid
            if n.z > -0.90:
                continue
            c = f.Center()
            bottom_candidates.append((c.z, -f.Area(), f))  # sort by z then by largest area
        except Exception:
            continue

    if not bottom_candidates:
        # Fallback: choose lowest planar face regardless of normal
        for f in faces:
            try:
                if getattr(f, "geomType", lambda: None)() != "PLANE":
                    continue
                c = f.Center()
                bottom_candidates.append((c.z, -f.Area(), f))
            except Exception:
                continue

    if not bottom_candidates:
        raise ValueError("Could not find a planar bottom reference face")

    bottom_candidates.sort()
    bottom_face = bottom_candidates[0][2]
    bottom_z = bottom_face.Center().z
    bottom_n = bottom_face.normalAt()
    print(f"Selected bottom face: center.z={bottom_z:.3f}, area={bottom_face.Area():.3f}, normal=({bottom_n.x:.3f},{bottom_n.y:.3f},{bottom_n.z:.3f})")

    # --- Determine the inner opening wire on that face ---
    # Prefer innerWires(); if not available/empty, fall back to picking smallest-area closed wire.
    def _wire_area(w):
        try:
            ff = cq.Face.makeFromWires(w)
            return abs(ff.Area())
        except Exception:
            return None

    inner_wires = []
    try:
        inner_wires = list(bottom_face.innerWires())
    except Exception:
        inner_wires = []

    if inner_wires:
        # choose the largest inner wire (sometimes there can be multiple holes; we want window opening)
        iw_areas = [( _wire_area(w) or 0.0, w) for w in inner_wires]
        iw_areas.sort(reverse=True)
        inner_wire = iw_areas[0][1]
        print(f"Bottom face innerWires(): {len(inner_wires)}; selected inner wire area={iw_areas[0][0]:.3f}")
    else:
        # fallback: use all wires on the face, pick the smallest as the hole
        all_wires = list(bottom_face.Wires())
        if len(all_wires) < 2:
            raise ValueError("Bottom face does not appear to have an inner opening wire")
        wire_infos = []
        for w in all_wires:
            a = _wire_area(w)
            if a is not None:
                wire_infos.append((a, w))
        wire_infos.sort()  # smallest first
        inner_wire = wire_infos[0][1]
        print(f"Bottom face Wires(): {len(all_wires)}; selected smallest wire as inner, area={wire_infos[0][0]:.3f}")

    # --- Parameters (model assumed to be in mm) ---
    offset_mm = 20.0   # 2 cm
    support_thk_mm = 5.0  # 0.5 cm
    top_fillet_mm = 2.0   # 0.2 cm

    # --- Build offset wire outward from inner opening ---
    wp_bottom = cq.Workplane(obj=bottom_face)

    def _offset_wire(dist):
        wpo = cq.Workplane(obj=bottom_face).add(inner_wire).offset2D(dist, kind="arc")
        ws = list(wpo.wires().vals())
        if not ws:
            raise ValueError("offset2D produced no wires")
        # pick the wire with largest area
        scored = []
        for w in ws:
            a = _wire_area(w)
            if a is not None:
                scored.append((a, w))
        if not scored:
            return ws[0]
        scored.sort(reverse=True)
        return scored[0][1]

    # try +offset then verify it enlarged vs original; if not, flip sign
    base_area = _wire_area(inner_wire) or 0.0
    ow_pos = _offset_wire(+offset_mm)
    ow_pos_area = _wire_area(ow_pos) or 0.0
    ow_neg = _offset_wire(-offset_mm)
    ow_neg_area = _wire_area(ow_neg) or 0.0

    # choose the offset that gives a larger area than base
    if ow_pos_area > base_area and ow_pos_area >= ow_neg_area:
        offset_wire = ow_pos
        chosen = "+"
        chosen_area = ow_pos_area
    elif ow_neg_area > base_area:
        offset_wire = ow_neg
        chosen = "-"
        chosen_area = ow_neg_area
    else:
        # if neither clearly bigger, just pick the bigger of the two
        offset_wire = ow_pos if ow_pos_area >= ow_neg_area else ow_neg
        chosen = "?"
        chosen_area = max(ow_pos_area, ow_neg_area)

    print(f"Inner wire area ~ {base_area:.3f}; offset(+){ow_pos_area:.3f}, offset(-){ow_neg_area:.3f} => chosen '{chosen}' with area {chosen_area:.3f}")

    # --- Create planar ring face between offset_wire (outer) and inner_wire (inner) ---
    ring_face = cq.Face.makeFromWires(offset_wire, [inner_wire])

    # --- Extrude downwards (global -Z). Determine sign based on bottom face normal ---
    # If bottom_face normal points -Z, positive extrude goes downward; else negative.
    extrude_amt = support_thk_mm if bottom_n.z < 0 else -support_thk_mm

    support = cq.Workplane(obj=bottom_face).add(ring_face).extrude(extrude_amt)

    # --- Apply fillets ONLY on the TOP edges of the new support (leave bottom edges sharp) ---
    sup_shape = support.val()
    sup_bb = sup_shape.BoundingBox()
    z_top = sup_bb.zmax
    z_bot = sup_bb.zmin
    print(f"Support bbox z[{z_bot:.3f},{z_top:.3f}] (top should coincide with bottom plane ~ {bottom_z:.3f})")

    tol = 1e-3
    def _edge_all_vertices_at_z(e, z):
        try:
            return all(abs(v.Center().z - z) < 0.02 for v in e.Vertices())
        except Exception:
            return False

    top_edges = [e for e in sup_shape.Edges() if _edge_all_vertices_at_z(e, z_top)]
    print(f"Support top-edge count candidate for fillet: {len(top_edges)}")

    if top_edges:
        support = cq.Workplane(obj=sup_shape).newObject([sup_shape]).edges().filter(lambda e: _edge_all_vertices_at_z(e, z_top)).fillet(top_fillet_mm)

    # --- Union support with original model ---
    result = cq.Workplane(obj=base_shape).union(support)

    # Note: removing pre-existing bottom radii on the imported base model is non-trivial in direct modeling.
    # This iteration focuses on: (1) adding the bottom support step, (2) keeping the NEW bottom edges sharp,
    # and (3) adding 2mm fillet on the TOP shoulder edges of the new support.

    return result
