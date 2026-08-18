def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args.get("input_file", ""))
    if not input_file or not os.path.exists(input_file):
        raise ValueError(f"Missing or invalid args['input_file']: {input_file}")

    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    solids = list(shape.Solids())
    print(f"Loaded STEP: {input_file}")
    print(f"Num solids: {len(solids)}")
    for i, s in enumerate(solids):
        bb = s.BoundingBox()
        print(f"  solid[{i}] vol={s.Volume():.3f} bbox=({bb.xlen:.2f},{bb.ylen:.2f},{bb.zlen:.2f})")

    if len(solids) < 1:
        raise ValueError("No solids found in STEP")

    # Housing is assumed to be the largest-volume solid
    solids_sorted = sorted(solids, key=lambda s: s.Volume(), reverse=True)
    housing = solids_sorted[0]
    insert = solids_sorted[1] if len(solids_sorted) > 1 else None

    hb = housing.BoundingBox()
    h_top_y = hb.ymax
    h_ctr = hb.center
    print(f"Housing bbox center=({h_ctr.x:.3f},{h_ctr.y:.3f},{h_ctr.z:.3f}) topY={h_top_y:.3f}")

    def safe_normal(face):
        c = face.Center()
        try:
            n = face.normalAt(c)
        except Exception:
            # fallback: try param-space normal
            try:
                n = face.normalAt(0, 0)
            except Exception:
                n = cq.Vector(0, 1, 0)
        ln = (n.Length or 1.0)
        return cq.Vector(n.x / ln, n.y / ln, n.z / ln)

    def edge_hash(e):
        # robust OCC hash
        try:
            return e.wrapped.HashCode(2147483647)
        except Exception:
            try:
                return e.HashCode(2147483647)
            except Exception:
                # last resort
                return id(e)

    def is_horizontal_edge(e, y_ratio_max=0.35):
        try:
            p1 = e.startPoint()
            p2 = e.endPoint()
            v = p2.sub(p1)
            L = v.Length
            if L < 1e-6:
                return False
            return abs(v.y) / L <= y_ratio_max
        except Exception:
            return True

    faces = list(housing.Faces())
    planar = []
    for f in faces:
        try:
            if f.geomType().upper() == "PLANE":
                planar.append(f)
        except Exception:
            # if geomType not available, skip
            pass

    print(f"Planar faces on housing: {len(planar)}")

    # Find pocket floor: a small-ish horizontal planar face in the upper half
    floor_candidates = []
    for f in planar:
        n = safe_normal(f)
        if abs(n.y) > 0.9:
            bb = f.BoundingBox()
            cy = bb.center.y
            # pocket floor should be in upper region (well above bottom)
            if cy > (hb.ymin + 0.25 * hb.ylen):
                # exclude very large planar faces (unlikely here, but safe)
                try:
                    area = f.Area()
                except Exception:
                    area = (bb.xlen * bb.zlen)
                floor_candidates.append((area, f))

    if not floor_candidates:
        print("No clear pocket-floor planar face found; will attempt direct edge selection from internal planar walls near top.")
        floor_face = None
        floor_edge_hashes = set()
    else:
        floor_candidates.sort(key=lambda t: t[0])
        floor_face = floor_candidates[0][1]
        fbb = floor_face.BoundingBox()
        print(f"Chosen floor face: area~{floor_candidates[0][0]:.3f} centerY={fbb.center.y:.3f} bboxY=({fbb.ymin:.3f},{fbb.ymax:.3f})")
        floor_edge_hashes = {edge_hash(e) for e in floor_face.Edges()}

    # Identify wall faces adjacent to floor (preferred). Fallback: vertical planar faces near model center/top.
    wall_faces = []
    if floor_face is not None:
        for f in planar:
            if f is floor_face:
                continue
            n = safe_normal(f)
            # drafted walls are mostly vertical; exclude near-horizontal
            if abs(n.y) < 0.35:
                # adjacency via shared edge hash
                shared = False
                for e in f.Edges():
                    if edge_hash(e) in floor_edge_hashes:
                        shared = True
                        break
                if shared:
                    wall_faces.append(f)
        print(f"Wall faces adjacent to floor: {len(wall_faces)}")

    if not wall_faces:
        # Fallback: pick vertical planar faces near center and near top
        cand = []
        for f in planar:
            n = safe_normal(f)
            if abs(n.y) < 0.35:
                bb = f.BoundingBox()
                c = bb.center
                # near top opening
                if bb.ymax > (h_top_y - 0.20 * hb.ylen):
                    # near center in XZ
                    dx = abs(c.x - h_ctr.x) / (hb.xlen + 1e-9)
                    dz = abs(c.z - h_ctr.z) / (hb.zlen + 1e-9)
                    try:
                        area = f.Area()
                    except Exception:
                        area = bb.xlen * bb.zlen
                    score = (dx + dz) + 0.0001 * area
                    cand.append((score, f))
        cand.sort(key=lambda t: t[0])
        wall_faces = [t[1] for t in cand[:6]]  # keep a few; we'll still pick correct edges per-face
        print(f"Fallback wall-face candidates: {len(wall_faces)}")

    # For each wall face, select its top mouth edge: highest horizontal edge not shared with floor
    edges_to_fillet = []
    used = set()
    for idx, wf in enumerate(wall_faces):
        best = None
        best_y = -1e99
        for e in wf.Edges():
            eh = edge_hash(e)
            if eh in used:
                continue
            if eh in floor_edge_hashes:
                continue
            if not is_horizontal_edge(e):
                continue
            ebb = e.BoundingBox()
            # Prefer edges very near the top opening region
            y_metric = ebb.ymax
            if y_metric > best_y:
                best_y = y_metric
                best = e
        if best is not None:
            used.add(edge_hash(best))
            edges_to_fillet.append(best)
            bb = best.BoundingBox()
            print(f"Selected edge from wall[{idx}] yMax={bb.ymax:.3f} yMin={bb.ymin:.3f} xLen={bb.xlen:.3f} zLen={bb.zlen:.3f}")

    print(f"Edges selected for fillet: {len(edges_to_fillet)}")

    if not edges_to_fillet:
        raise ValueError("Failed to identify slot-mouth edges for filleting")

    # Apply 2mm fillet on housing only
    housing_wp = cq.Workplane(obj=housing)
    housing_fillet_wp = housing_wp.newObject(edges_to_fillet).fillet(2.0)
    housing_fillet = housing_fillet_wp.val()

    # Return both solids (housing modified, insert unchanged)
    if insert is not None:
        assy = cq.Assembly()
        assy.add(housing_fillet, name="housing")
        assy.add(insert, name="insert")
        return assy

    return housing_fillet
