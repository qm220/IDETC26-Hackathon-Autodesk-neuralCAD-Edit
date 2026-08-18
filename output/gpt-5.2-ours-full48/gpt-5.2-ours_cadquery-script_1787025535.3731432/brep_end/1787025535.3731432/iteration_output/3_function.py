def my_cad_function(args):
    import cadquery as cq
    import os
    from math import sqrt, pi

    # ---------------- Helpers ----------------
    def _unit(v: cq.Vector) -> cq.Vector:
        L = v.Length
        if L == 0:
            return cq.Vector(0, 0, 0)
        return cq.Vector(v.x / L, v.y / L, v.z / L)

    def _dot(a: cq.Vector, b: cq.Vector) -> float:
        return a.x * b.x + a.y * b.y + a.z * b.z

    def _dist(a: cq.Vector, b: cq.Vector) -> float:
        dx, dy, dz = a.x - b.x, a.y - b.y, a.z - b.z
        return sqrt(dx * dx + dy * dy + dz * dz)

    def _coord(p: cq.Vector, idx: int) -> float:
        return (p.x, p.y, p.z)[idx]

    def _set_coord(p: cq.Vector, idx: int, val: float) -> cq.Vector:
        if idx == 0:
            return cq.Vector(val, p.y, p.z)
        if idx == 1:
            return cq.Vector(p.x, val, p.z)
        return cq.Vector(p.x, p.y, val)

    def _face_plane(face: cq.Face):
        """Return (point_on_plane, unit_normal) for planar faces else (None, None)."""
        try:
            from OCP.BRepAdaptor import BRepAdaptor_Surface
            from OCP.GeomAbs import GeomAbs_Plane

            ad = BRepAdaptor_Surface(face.wrapped)
            if ad.GetType() != GeomAbs_Plane:
                return None, None
            pln = ad.Plane()
            loc = pln.Location()
            n_dir = pln.Axis().Direction()
            p = cq.Vector(loc.X(), loc.Y(), loc.Z())
            n = _unit(cq.Vector(n_dir.X(), n_dir.Y(), n_dir.Z()))
            return p, n
        except Exception:
            return None, None

    def _circle_edge_data(edge: cq.Edge):
        """Return (radius, center_point, axis_dir_unit, u0, u1) for circular edges else None."""
        try:
            from OCP.BRepAdaptor import BRepAdaptor_Curve
            from OCP.GeomAbs import GeomAbs_Circle

            ad = BRepAdaptor_Curve(edge.wrapped)
            if ad.GetType() != GeomAbs_Circle:
                return None
            circ = ad.Circle()
            r = float(circ.Radius())
            ax = circ.Axis()
            loc = ax.Location()
            d = ax.Direction()
            c = cq.Vector(loc.X(), loc.Y(), loc.Z())
            v = _unit(cq.Vector(d.X(), d.Y(), d.Z()))
            u0 = float(ad.FirstParameter())
            u1 = float(ad.LastParameter())
            return r, c, v, u0, u1
        except Exception:
            return None

    def _is_full_circle(u0: float, u1: float, tol=0.25):
        # For circle curves, parameters are angles (radians). Full circle span ~ 2*pi.
        span = abs(u1 - u0)
        # normalize large spans
        while span > 2 * pi:
            span -= 2 * pi
        return abs(span - 2 * pi) < tol

    def _unique_by_center(items, tol=0.02):
        # items: list of (r, center)
        out = []
        for r, c in items:
            if all(_dist(c, oc) > tol for _, oc in out):
                out.append((r, c))
        return out

    def _pick_4_spread(points):
        """Greedy farthest-point selection to get up to 4 well-spread points."""
        pts = list(points)
        if len(pts) <= 4:
            return pts
        best_i, best_j, best_d = 0, 1, -1
        for i in range(len(pts)):
            for j in range(i + 1, len(pts)):
                d = _dist(pts[i], pts[j])
                if d > best_d:
                    best_d = d
                    best_i, best_j = i, j
        chosen = [pts[best_i], pts[best_j]]
        remaining = [p for k, p in enumerate(pts) if k not in (best_i, best_j)]
        while len(chosen) < 4 and remaining:
            best_p, best_md = None, -1
            for p in remaining:
                md = min(_dist(p, q) for q in chosen)
                if md > best_md:
                    best_md = md
                    best_p = p
            chosen.append(best_p)
            remaining = [p for p in remaining if _dist(p, best_p) > 1e-9]
        return chosen

    # ---------------- Load STEP ----------------
    if "input_file" not in args:
        raise ValueError("Expected args['input_file']")
    input_file = os.path.expanduser(args["input_file"])
    wp = cq.importers.importStep(input_file)
    shape = wp.val() if hasattr(wp, "val") else wp

    bbox = shape.BoundingBox()
    xlen, ylen, zlen = bbox.xlen, bbox.ylen, bbox.zlen
    diag = sqrt(xlen * xlen + ylen * ylen + zlen * zlen)
    maxdim = max(xlen, ylen, zlen)
    print(f"BBOX lens: x={xlen:.3f} y={ylen:.3f} z={zlen:.3f} diag={diag:.3f}")

    # Thickness axis = smallest bbox dimension
    lens = [(xlen, 0), (ylen, 1), (zlen, 2)]
    t_idx = sorted(lens, key=lambda a: a[0])[0][1]
    thickness_axis = _unit([cq.Vector(1, 0, 0), cq.Vector(0, 1, 0), cq.Vector(0, 0, 1)][t_idx])

    min_coord = [bbox.xmin, bbox.ymin, bbox.zmin][t_idx]
    max_coord = [bbox.xmax, bbox.ymax, bbox.zmax][t_idx]
    t_len = [xlen, ylen, zlen][t_idx]
    print(f"Thickness axis index={t_idx} vec=({thickness_axis.x:.1f},{thickness_axis.y:.1f},{thickness_axis.z:.1f})")
    print(f"Thickness min={min_coord:.4f} max={max_coord:.4f} len={t_len:.4f}")

    # ---------------- Units heuristic ----------------
    # This part looks like a real bracket; a max dimension ~10..30 strongly suggests the STEP is in cm.
    if maxdim < 30:
        mm_to_model = 0.1
        print("Units heuristic: treating model units as cm (Fusion STEP common); 1 mm = 0.1 model units")
    else:
        mm_to_model = 1.0
        print("Units heuristic: treating model units as mm; 1 mm = 1.0 model units")

    # ---------------- Find bottom base planar face ----------------
    faces = list(shape.Faces())
    bottom_face = None
    bottom_area = -1
    eps_bottom = max(1e-4, 0.01 * t_len)

    for f in faces:
        p0, n = _face_plane(f)
        if p0 is None:
            continue
        if abs(_dot(n, thickness_axis)) < 0.98:
            continue
        ctr = f.Center()
        c = cq.Vector(ctr.x, ctr.y, ctr.z)
        if abs(_coord(c, t_idx) - min_coord) > eps_bottom:
            continue
        a = f.Area()
        if a > bottom_area:
            bottom_area = a
            bottom_face = f

    if bottom_face is None:
        print("WARNING: Could not identify bottom planar contact face; groove placement may be unreliable.")
    else:
        bc = bottom_face.Center()
        print(f"Bottom planar face picked: area={bottom_area:.3f} center=({bc.x:.3f},{bc.y:.3f},{bc.z:.3f})")

    # ---------------- Mounting hole detection (from bottom face full circles) ----------------
    mount_centers = []
    mount_r = None
    if bottom_face is not None:
        circ_edges = []  # (r, center)
        # Use only edges belonging to the bottom planar face, and only full circles.
        for e in bottom_face.Edges():
            cd = _circle_edge_data(e)
            if cd is None:
                continue
            r, c, ax, u0, u1 = cd
            if abs(_dot(ax, thickness_axis)) < 0.98:
                continue
            if not _is_full_circle(u0, u1):
                continue
            # project center onto the bottom plane coordinate
            c_proj = _set_coord(c, t_idx, min_coord)
            circ_edges.append((r, c_proj))

        circ_edges = _unique_by_center(circ_edges, tol=max(1e-3, 0.002 * maxdim))
        print(f"Bottom-face full-circle candidates: {len(circ_edges)}")

        # Cluster by radius
        clusters = []
        for r, c in sorted(circ_edges, key=lambda t: t[0]):
            placed = False
            for cl in clusters:
                tol = 0.05 * max(r, cl["r"])  # 5% tolerance
                if abs(r - cl["r"]) <= tol:
                    cl["items"].append((r, c))
                    cl["r"] = sum(rr for rr, _ in cl["items"]) / len(cl["items"])
                    placed = True
                    break
            if not placed:
                clusters.append({"r": r, "items": [(r, c)]})

        # Prefer a 4-count cluster within a reasonable size range
        plausible = []
        for cl in clusters:
            rnom = cl["r"]
            cnt = len(cl["items"])
            if cnt < 4:
                continue
            # reject huge radii (typically perimeter rounds)
            if not (0.005 * maxdim <= rnom <= 0.15 * maxdim):
                continue
            plausible.append(cl)

        if not plausible:
            print("WARNING: No plausible 4-hole radius cluster found on bottom face; skipping grooves.")
        else:
            # prefer count==4 if present, else use the largest count but pick 4 most-spread
            plausible.sort(key=lambda cl: (0 if len(cl["items"]) == 4 else 1, -len(cl["items"]), -cl["r"]))
            cl = plausible[0]
            mount_r = cl["r"]
            pts = [c for _, c in cl["items"]]
            mount_centers = _pick_4_spread(pts)
            print(f"Mount-hole cluster: r~{mount_r:.4f} items={len(cl['items'])}; using centers={len(mount_centers)}")
            for i, c in enumerate(mount_centers):
                print(f"  mount_center[{i}] = ({c.x:.3f},{c.y:.3f},{c.z:.3f})")

    # ---------------- Find underside pocket floor planar face ----------------
    pocket_floor_face = None
    pocket_floor_area = -1

    for f in faces:
        p0, n = _face_plane(f)
        if p0 is None:
            continue
        if abs(_dot(n, thickness_axis)) < 0.98:
            continue
        ctr = f.Center()
        c = cq.Vector(ctr.x, ctr.y, ctr.z)
        cth = _coord(c, t_idx)
        # must be above bottom, but not near the top
        if cth < (min_coord + 0.05 * t_len) or cth > (min_coord + 0.70 * t_len):
            continue
        # prefer faces that are internal (smaller than full footprint)
        fb = f.BoundingBox()
        if fb.xlen > 0.98 * xlen or fb.zlen > 0.98 * zlen:
            continue
        a = f.Area()
        if a > pocket_floor_area:
            pocket_floor_area = a
            pocket_floor_face = f

    if pocket_floor_face is None:
        # fallback: use bbox center, slightly above bottom
        hole_center = cq.Vector((bbox.xmin + bbox.xmax) / 2.0,
                                (bbox.ymin + bbox.ymax) / 2.0,
                                (bbox.zmin + bbox.zmax) / 2.0)
        hole_center = _set_coord(hole_center, t_idx, min_coord + 0.25 * t_len)
        print("WARNING: pocket floor face not found; using a mid-thickness bbox-derived point for connecting hole.")
    else:
        hc = pocket_floor_face.Center()
        hole_center = cq.Vector(hc.x, hc.y, hc.z)
        print(f"Pocket floor face picked: area={pocket_floor_area:.3f} center=({hole_center.x:.3f},{hole_center.y:.3f},{hole_center.z:.3f})")

    result = shape

    # ---------------- Operation 1: connecting hole Ø1.7mm ----------------
    hole_d = 1.7 * mm_to_model
    hole_r = hole_d / 2.0
    cut_len = max(2.5 * t_len, 4.0 * diag)
    # Start slightly below the pocket floor plane to ensure the cut opens into the pocket volume
    base_p = hole_center - thickness_axis * (0.2 * mm_to_model)
    hole_cyl = cq.Solid.makeCylinder(hole_r, cut_len, base_p, thickness_axis)
    result = result.cut(hole_cyl)
    print(f"Connecting hole cut: diameter={hole_d:.4f} at ({hole_center.x:.3f},{hole_center.y:.3f},{hole_center.z:.3f})")

    # ---------------- Operation 2: grooves 0.1mm deep/0.1mm wide (3 rings per hole) ----------------
    if mount_r is None or len(mount_centers) != 4:
        print("WARNING: mounting holes not reliably detected; grooves skipped.")
        return cq.Workplane("XY").newObject([result])

    groove_depth = 0.1 * mm_to_model
    groove_w = 0.1 * mm_to_model
    rings_per_hole = 3
    start_offset = 0.3 * mm_to_model
    pitch = 0.2 * mm_to_model

    groove_solids = []

    for c in mount_centers:
        # ensure grooves start exactly on the bottom contact plane
        c0 = _set_coord(c, t_idx, min_coord)
        for i in range(rings_per_hole):
            inner_r = mount_r + start_offset + i * pitch
            outer_r = inner_r + groove_w
            outer = cq.Solid.makeCylinder(outer_r, groove_depth, c0, thickness_axis)
            inner = cq.Solid.makeCylinder(inner_r, groove_depth, c0, thickness_axis)
            groove_solids.append(outer.cut(inner))

    g = groove_solids[0]
    for s in groove_solids[1:]:
        g = g.fuse(s)

    result = result.cut(g)
    print(f"Grooves cut: depth={groove_depth:.4f} width={groove_w:.4f} rings={len(groove_solids)}")

    print("Edit complete (connecting hole + grooves).")
    return cq.Workplane("XY").newObject([result])
