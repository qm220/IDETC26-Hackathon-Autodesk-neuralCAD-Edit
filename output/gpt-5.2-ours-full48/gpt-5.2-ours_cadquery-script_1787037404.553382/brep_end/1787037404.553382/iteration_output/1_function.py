def my_cad_function(args):
    import cadquery as cq
    import os, math

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

    # --- Determine thickness axis as the smallest bbox dimension (frame thickness direction) ---
    lens = {"X": bb.xlen, "Y": bb.ylen, "Z": bb.zlen}
    thickness_axis = min(lens, key=lens.get)
    axis_vecs = {"X": (1.0, 0.0, 0.0), "Y": (0.0, 1.0, 0.0), "Z": (0.0, 0.0, 1.0)}
    ax = axis_vecs[thickness_axis]

    def coord_of(pt, axis_name):
        return getattr(pt, axis_name.lower())

    axis_min = {"X": bb.xmin, "Y": bb.ymin, "Z": bb.zmin}[thickness_axis]
    axis_max = {"X": bb.xmax, "Y": bb.ymax, "Z": bb.zmax}[thickness_axis]

    # Convention for this edit:
    # - "Bottom" is at minimum coordinate along the thickness axis
    # - "Top" is at maximum coordinate along the thickness axis
    bottom_coord = axis_min
    top_coord = axis_max
    print(f"Inferred thickness axis: {thickness_axis} (len={lens[thickness_axis]:.3f})")
    print(f"Bottom coord along {thickness_axis}: {bottom_coord:.3f}; Top coord: {top_coord:.3f}")

    # --- Helpers ---
    def wire_area(w):
        try:
            return abs(cq.Face.makeFromWires(w).Area())
        except Exception:
            return None

    def make_plane_at(axis_name, axis_value, normal_vec):
        # Plane passing through model center, positioned at axis_value
        cx = 0.5 * (bb.xmin + bb.xmax)
        cy = 0.5 * (bb.ymin + bb.ymax)
        cz = 0.5 * (bb.zmin + bb.zmax)
        origin = [cx, cy, cz]
        idx = {"X": 0, "Y": 1, "Z": 2}[axis_name]
        origin[idx] = axis_value

        n = cq.Vector(*normal_vec)
        if n.Length == 0:
            raise ValueError("Zero normal")
        n = n.normalized()

        ref = cq.Vector(1, 0, 0) if abs(n.dot(cq.Vector(1, 0, 0))) < 0.9 else cq.Vector(0, 0, 1)
        xdir = ref.cross(n)
        if xdir.Length == 0:
            ref = cq.Vector(0, 1, 0)
            xdir = ref.cross(n)
        xdir = xdir.normalized()

        return cq.Plane(origin=tuple(origin), xDir=xdir.toTuple(), normal=n.toTuple())

    # --- Try to find a bottom planar broad face with an inner opening (annular face) ---
    faces = list(shape.Faces())
    print(f"Face count: {len(faces)}")

    bottom_face = None
    bottom_face_has_inner = False

    # candidates: planar faces whose normals are close to +/- thickness axis
    cand = []
    for f in faces:
        try:
            if getattr(f, "geomType", lambda: None)() != "PLANE":
                continue
            n = f.normalAt()
            dot = abs(n.x * ax[0] + n.y * ax[1] + n.z * ax[2])
            if dot < 0.90:
                continue
            c = f.Center()
            d_to_bottom = abs(coord_of(c, thickness_axis) - bottom_coord)
            has_inner = False
            try:
                has_inner = len(list(f.innerWires())) > 0
            except Exception:
                has_inner = False
            cand.append((0 if has_inner else 1, d_to_bottom, -f.Area(), f, has_inner, dot, coord_of(c, thickness_axis)))
        except Exception:
            continue

    cand.sort(key=lambda t: (t[0], t[1], t[2]))
    if cand:
        bottom_face = cand[0][3]
        bottom_face_has_inner = cand[0][4]
        print(
            f"Selected bottom candidate face: has_inner={bottom_face_has_inner}, "
            f"center.{thickness_axis.lower()}={cand[0][6]:.3f}, area={bottom_face.Area():.3f}, dot={cand[0][5]:.3f}"
        )
    else:
        print("No planar faces aligned with inferred thickness axis were found; will fall back to section method.")

    # --- Obtain inner opening wire (window) profile ---
    inner_wire = None

    if bottom_face is not None and bottom_face_has_inner:
        inner_wires = list(bottom_face.innerWires())
        scored = []
        for w in inner_wires:
            a = wire_area(w)
            scored.append((a if a is not None else 0.0, w))
        scored.sort(reverse=True)
        inner_wire = scored[0][1]
        print(f"Using innerWire from bottom face. innerWires={len(inner_wires)}; chosen_area={scored[0][0]:.3f}")

        # Also set the support sketch plane at the actual bottom coordinate
        # Use outward normal = -thickness_axis direction
        outward = (-ax[0], -ax[1], -ax[2])
        plane_support = make_plane_at(thickness_axis, bottom_coord, outward)

    else:
        # Fall back: section the solid slightly above the bottom to get loops,
        # then translate the selected inner loop down onto the bottom plane.
        eps = 0.5  # mm into the part
        section_coord = bottom_coord + eps

        # Section plane normal along +axis (doesn't matter for intersection)
        plane_section = make_plane_at(thickness_axis, section_coord, ax)
        sec = cq.Workplane(plane_section).add(shape).section()
        wires = list(sec.wires().vals())
        print(f"Section wires at {thickness_axis}={section_coord:.3f}: {len(wires)}")
        if len(wires) < 2:
            raise ValueError("Could not derive inner/outer loops from section; not enough wires")

        # pick smallest-area closed wire as inner opening
        scored = []
        for w in wires:
            a = wire_area(w)
            if a is not None:
                scored.append((a, w))
        if not scored:
            raise ValueError("Section produced wires but could not compute any wire areas")
        scored.sort(key=lambda t: t[0])
        inner_wire = scored[0][1]
        print(f"Chosen inner wire from section: area={scored[0][0]:.3f}")

        # Translate inner wire from section plane to bottom plane
        delta = bottom_coord - section_coord
        move_vec = cq.Vector(ax[0] * delta, ax[1] * delta, ax[2] * delta)
        inner_wire = inner_wire.translate(move_vec)

        outward = (-ax[0], -ax[1], -ax[2])
        plane_support = make_plane_at(thickness_axis, bottom_coord, outward)

    # --- Parameters (assume model units are mm) ---
    offset_mm = 20.0   # 2 cm
    support_thk_mm = 5.0  # 0.5 cm
    top_fillet_mm = 2.0   # 0.2 cm

    # --- Offset inner opening outward by 20mm (choose sign that increases area) ---
    base_a = wire_area(inner_wire) or 0.0

    def offset_wire(dist):
        wpo = cq.Workplane(plane_support).add(inner_wire).offset2D(dist, kind="arc")
        ws = list(wpo.wires().vals())
        if not ws:
            raise ValueError("offset2D produced no wires")
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

    ow_pos = offset_wire(+offset_mm)
    ow_neg = offset_wire(-offset_mm)
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

    # ensure it is truly outward (larger area); if not, still proceed with larger-of-two
    print(f"Inner area={base_a:.3f}; offset(+)={a_pos:.3f}, offset(-)={a_neg:.3f} => chosen {chosen} (area={chosen_a:.3f})")

    # --- Create annular face and extrude OUTWARD from bottom by 5mm to form support ring ---
    ring_face = cq.Face.makeFromWires(offset_outer, [inner_wire])
    support = cq.Workplane(plane_support).add(ring_face).extrude(support_thk_mm)

    sup_shape = support.val()
    sup_bb = sup_shape.BoundingBox()
    # Determine top coordinate of support along thickness axis (the interface shoulder plane)
    sup_top = {"X": sup_bb.xmax, "Y": sup_bb.ymax, "Z": sup_bb.zmax}[thickness_axis]
    sup_bot = {"X": sup_bb.xmin, "Y": sup_bb.ymin, "Z": sup_bb.zmin}[thickness_axis]
    print(f"Support bbox along {thickness_axis}: [{sup_bot:.3f},{sup_top:.3f}] (expected top ~ {bottom_coord:.3f})")

    # --- Fillet ONLY the top shoulder edges of the new support (leave bottom edges sharp) ---
    tol = 0.05  # mm

    def edge_vertices_all_at_coord(e, axis_name, target):
        try:
            for v in e.Vertices():
                if abs(coord_of(v.Center(), axis_name) - target) > tol:
                    return False
            return True
        except Exception:
            return False

    # Apply fillet on edges lying on the top of the support (shoulder). Exclude bottom edges.
    top_edges_count = sum(1 for e in sup_shape.Edges() if edge_vertices_all_at_coord(e, thickness_axis, sup_top))
    bot_edges_count = sum(1 for e in sup_shape.Edges() if edge_vertices_all_at_coord(e, thickness_axis, sup_bot))
    print(f"Support candidate edges: top={top_edges_count}, bottom={bot_edges_count}")

    if top_edges_count > 0:
        support = (
            cq.Workplane(obj=sup_shape)
            .newObject([sup_shape])
            .edges()
            .filter(lambda e: edge_vertices_all_at_coord(e, thickness_axis, sup_top))
            .fillet(top_fillet_mm)
        )

    # --- Union with original ---
    result = cq.Workplane(obj=shape).union(support)

    # Note: removing existing bottom radii on the imported base model is not reliably possible
    # without feature history; this script ensures NEW bottom edges of the added support remain sharp.

    return result
