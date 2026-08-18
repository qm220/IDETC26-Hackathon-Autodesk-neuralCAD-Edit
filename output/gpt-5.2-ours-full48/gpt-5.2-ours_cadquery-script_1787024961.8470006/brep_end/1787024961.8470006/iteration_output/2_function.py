def my_cad_function(args):
    import cadquery as cq
    import os
    import statistics

    if "input_file" not in args:
        raise ValueError("args['input_file'] is required for this edit task")

    input_path = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_path)

    # Normalize import to a single Shape
    if isinstance(imported, cq.Workplane):
        root_shape = imported.val()
    elif hasattr(cq, "Assembly") and isinstance(imported, cq.Assembly):
        root_shape = imported.toCompound()
    else:
        root_shape = imported

    wp = cq.Workplane(obj=root_shape)

    YP = cq.Vector(0, 1, 0)
    YM = cq.Vector(0, -1, 0)
    XP = cq.Vector(1, 0, 0)

    def vdot(a, b):
        return a.x * b.x + a.y * b.y + a.z * b.z

    def safe_unit(v):
        try:
            return v.normalized()
        except Exception:
            m = (v.x * v.x + v.y * v.y + v.z * v.z) ** 0.5
            if m == 0:
                return cq.Vector(0, 0, 0)
            return cq.Vector(v.x / m, v.y / m, v.z / m)

    def face_is_plane(f):
        try:
            return f.geomType() == "PLANE"
        except Exception:
            return False

    def face_normal_plane(f):
        # Only intended for planar faces
        try:
            pln = f.toPln()
            return safe_unit(pln.zDir)
        except Exception:
            # Fallback attempt
            try:
                c = f.Center()
                n = f.normalAt(c)
                return safe_unit(n)
            except Exception:
                return cq.Vector(0, 0, 0)

    def circle_edges_of_face(f):
        out = []
        for e in f.Edges():
            try:
                if e.geomType() == "CIRCLE":
                    out.append(e)
            except Exception:
                continue
        return out

    def edge_radius(e):
        try:
            return float(e.radius())
        except Exception:
            return None

    def dedup_edges(edges):
        uniq = []
        seen = set()
        for e in edges:
            try:
                k = e.hashCode(2147483647)
            except Exception:
                k = id(e)
            if k in seen:
                continue
            seen.add(k)
            uniq.append(e)
        return uniq

    faces = list(root_shape.Faces())
    plane_faces = [f for f in faces if face_is_plane(f)]
    print(f"[DBG] Total faces: {len(faces)} | planar: {len(plane_faces)}")

    # --- Find bottom datum face: largest planar face with normal ~ -Y ---
    bottom_face = None
    bottom_area = -1.0
    for f in plane_faces:
        n = face_normal_plane(f)
        if vdot(n, YM) > 0.98:
            try:
                a = f.Area()
            except Exception:
                continue
            if a > bottom_area:
                bottom_area = a
                bottom_face = f

    bottom_circle_edges = []
    bottom_radii = []
    if bottom_face is not None:
        bottom_circle_edges = circle_edges_of_face(bottom_face)
        for e in bottom_circle_edges:
            r = edge_radius(e)
            if r is not None:
                bottom_radii.append(r)

    print(f"[DBG] Bottom face found: {bottom_face is not None}, area={bottom_area:.6f}")
    print(f"[DBG] Bottom-face circular edges: {len(bottom_circle_edges)}")

    # --- Units inference from bottom-hole radii if possible ---
    units = None
    bottom_med_r = None
    if bottom_radii:
        bottom_med_r = statistics.median(bottom_radii)
        # If bottom hole radii are ~0.2..1.0 => likely inches; if ~5..30 => mm
        units = "mm" if bottom_med_r > 2.0 else "inch"
        print(f"[DBG] Bottom circle radii (sample): min={min(bottom_radii):.6f}, med={bottom_med_r:.6f}, max={max(bottom_radii):.6f} => units={units}")
    else:
        # Fallback heuristic from bbox
        try:
            bb = root_shape.BoundingBox()
            max_dim = max(bb.xlen, bb.ylen, bb.zlen)
            units = "inch" if max_dim < 50 else "mm"
            print(f"[DBG] Units fallback from BBox max={max_dim:.6f} => units={units}")
        except Exception as e:
            units = "inch"
            print(f"[WARN] Units fallback failed ({e}); defaulting to inches")

    chamfer_mm = 0.2
    chamfer_size = chamfer_mm if units == "mm" else chamfer_mm / 25.4
    print(f"[DBG] Chamfer size in model units: {chamfer_size:.8f} ({units})")

    # --- Collect target edges (hole edges) ---
    target_edges = []

    # (A) Mounting holes - bottom exits: circular edges on the bottom datum face
    target_edges.extend(bottom_circle_edges)

    # (B) Mounting holes - top entrances: annular boss-top faces (planar +Y) having exactly 2 circular edges
    # Pick the smaller of the 2 circles (the hole edge), not the boss OD.
    top_annular_faces = []
    if bottom_face is not None:
        # Use bottom area to scale a reasonable "small face" threshold
        small_face_area_limit = bottom_area * 0.08
    else:
        small_face_area_limit = None

    for f in plane_faces:
        n = face_normal_plane(f)
        if vdot(n, YP) <= 0.98:
            continue
        try:
            a = f.Area()
        except Exception:
            continue
        if small_face_area_limit is not None and a > small_face_area_limit:
            continue
        circs = circle_edges_of_face(f)
        if len(circs) != 2:
            continue
        # choose smaller-radius circle edge
        r0 = edge_radius(circs[0])
        r1 = edge_radius(circs[1])
        if r0 is None or r1 is None:
            continue
        inner = circs[0] if r0 < r1 else circs[1]
        top_annular_faces.append(f)
        target_edges.append(inner)

    print(f"[DBG] Top annular (boss seat) faces detected: {len(top_annular_faces)}")

    # (C) Clevis pin holes - both sides: circular edges on planar faces with normals ~ +/-X
    # Filter by being 'larger' than mounting holes if we have bottom_med_r.
    x_faces = []
    x_circle_edges = []
    for f in plane_faces:
        n = face_normal_plane(f)
        if abs(vdot(n, XP)) <= 0.98:
            continue
        circs = circle_edges_of_face(f)
        if not circs:
            continue
        x_faces.append(f)
        for e in circs:
            r = edge_radius(e)
            if r is None:
                continue
            if bottom_med_r is not None:
                # pin hole expected bigger than mounting holes
                if r >= bottom_med_r * 1.15:
                    x_circle_edges.append(e)
            else:
                x_circle_edges.append(e)

    print(f"[DBG] X-normal planar faces with circles: {len(x_faces)}")
    print(f"[DBG] Candidate clevis pin-hole circular edges on X-faces: {len(x_circle_edges)}")

    target_edges.extend(x_circle_edges)

    # De-duplicate
    target_edges = dedup_edges(target_edges)

    # Basic reporting
    targ_r = [edge_radius(e) for e in target_edges]
    targ_r = [r for r in targ_r if r is not None]
    if targ_r:
        print(f"[DBG] Total target circular edges for chamfer: {len(target_edges)} | radii min/med/max = {min(targ_r):.6f}/{statistics.median(targ_r):.6f}/{max(targ_r):.6f}")
    else:
        print(f"[DBG] Total target circular edges for chamfer: {len(target_edges)}")

    if len(target_edges) == 0:
        print("[WARN] No target hole edges found; no chamfer applied.")
        return wp

    # Apply equal-distance chamfer (45deg)
    try:
        result = wp.newObject(target_edges).chamfer(chamfer_size)
        print("[DBG] Chamfer applied.")
        return result
    except Exception as e:
        print(f"[ERROR] Chamfer failed on selected edges: {e}")
        # As a fallback, do nothing (to avoid corrupting the model)
        return wp
