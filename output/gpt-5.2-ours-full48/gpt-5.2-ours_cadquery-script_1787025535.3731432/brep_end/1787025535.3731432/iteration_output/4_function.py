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

    def _dist_xz(a: cq.Vector, b: cq.Vector) -> float:
        dx, dz = a.x - b.x, a.z - b.z
        return sqrt(dx * dx + dz * dz)

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
        span = abs(u1 - u0)
        while span > 2 * pi:
            span -= 2 * pi
        return abs(span - 2 * pi) < tol

    def _unique_by_center(items, tol=0.02):
        out = []
        for r, c in items:
            if all(_dist(c, oc) > tol for _, oc in out):
                out.append((r, c))
        return out

    def _pick_4_spread(points):
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
    if maxdim < 30:
        mm_to_model = 0.1
        print("Units heuristic: treating model units as cm (Fusion STEP common); 1 mm = 0.1 model units")
    else:
        mm_to_model = 1.0
        print("Units heuristic: treating model units as mm; 1 mm = 1.0 model units")

    faces = list(shape.Faces())

    # ---------------- Find bottom base planar face ----------------
    bottom_face = None
    bottom_area = -1
    eps_bottom = max(1e-4, 0.01 * t_len)

    for f in faces:
        p0, n = _face_plane(f)
        if p0 is None:
            continue
        if abs(_dot(n, thickness_axis)) < 0.98:
            continue
        c = f.Center()
        cc = cq.Vector(c.x, c.y, c.z)
        if abs(_coord(cc, t_idx) - min_coord) > eps_bottom:
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
        for e in bottom_face.Edges():
            cd = _circle_edge_data(e)
            if cd is None:
                continue
            r, c, ax, u0, u1 = cd
            if abs(_dot(ax, thickness_axis)) < 0.98:
                continue
            if not _is_full_circle(u0, u1):
                continue
            c_proj = _set_coord(c, t_idx, min_coord)
            circ_edges.append((r, c_proj))

        circ_edges = _unique_by_center(circ_edges, tol=max(1e-3, 0.002 * maxdim))
        print(f"Bottom-face full-circle candidates: {len(circ_edges)}")

        # cluster by radius
        clusters = []
        for r, c in sorted(circ_edges, key=lambda t: t[0]):
            placed = False
            for cl in clusters:
                tol = 0.05 * max(r, cl["r"])
                if abs(r - cl["r"]) <= tol:
                    cl["items"].append((r, c))
                    cl["r"] = sum(rr for rr, _ in cl["items"]) / len(cl["items"])
                    placed = True
                    break
            if not placed:
                clusters.append({"r": r, "items": [(r, c)]})

        plausible = []
        for cl in clusters:
            rnom, cnt = cl["r"], len(cl["items"])
            if cnt < 4:
                continue
            if not (0.005 * maxdim <= rnom <= 0.15 * maxdim):
                continue
            plausible.append(cl)

        if plausible:
            plausible.sort(key=lambda cl: (0 if len(cl["items"]) == 4 else 1, -len(cl["items"]), -cl["r"]))
            cl = plausible[0]
            mount_r = cl["r"]
            pts = [c for _, c in cl["items"]]
            mount_centers = _pick_4_spread(pts)
            print(f"Mount-hole cluster: r~{mount_r:.4f} items={len(cl['items'])}; using centers={len(mount_centers)}")
            for i, c in enumerate(mount_centers):
                print(f"  mount_center[{i}] = ({c.x:.3f},{c.y:.3f},{c.z:.3f})")
        else:
            print("WARNING: No plausible 4-hole radius cluster found on bottom face; grooves may be skipped.")

    # ---------------- Improved underside pocket floor planar face selection ----------------
    pocket_floor_face = None
    best_score = -1
    midx = 0.5 * (bbox.xmin + bbox.xmax)
    midz = 0.5 * (bbox.zmin + bbox.zmax)
    center_ref = cq.Vector(midx, 0, midz)

    for f in faces:
        p0, n = _face_plane(f)
        if p0 is None:
            continue
        if abs(_dot(n, thickness_axis)) < 0.98:
            continue

        ctr = f.Center()
        c = cq.Vector(ctr.x, ctr.y, ctr.z)
        cth = _coord(c, t_idx)

        # must be above bottom, and not near top
        if cth < (min_coord + 0.08 * t_len) or cth > (min_coord + 0.80 * t_len):
            continue

        a = f.Area()
        if a <= 0:
            continue

        # Count circular edges: pocket floor should usually have none; spotfaces/shoulders have circles.
        n_circ = 0
        for e in f.Edges():
            cd = _circle_edge_data(e)
            if cd is None:
                continue
            n_circ += 1

        # Prefer faces that are centrally located in X/Z
        dx = abs(c.x - midx) / max(1e-9, xlen)
        dz = abs(c.z - midz) / max(1e-9, zlen)
        normd = sqrt(dx * dx + dz * dz)
        center_w = 1.0 / (1.0 + 6.0 * normd)

        # Penalize circular-edged faces heavily (mount spotfaces)
        circ_pen = 1.0 / (1.0 + 6.0 * n_circ)

        # Slight preference for larger faces (pocket floor should be relatively large)
        score = a * center_w * circ_pen

        if score > best_score:
            best_score = score
            pocket_floor_face = f

    if pocket_floor_face is None:
        print("WARNING: pocket floor face not found; using bbox center as fallback for connecting hole.")
        hole_center = cq.Vector(midx, 0.5 * (bbox.ymin + bbox.ymax), midz)
        hole_center = _set_coord(hole_center, t_idx, min_coord + 0.25 * t_len)
    else:
        hc = pocket_floor_face.Center()
        hole_center = cq.Vector(hc.x, hc.y, hc.z)
        # Debug: how circular is the chosen face?
        n_circ_dbg = 0
        for e in pocket_floor_face.Edges():
            if _circle_edge_data(e) is not None:
                n_circ_dbg += 1
        print(
            f"Pocket floor face picked (improved): area={pocket_floor_face.Area():.3f} center=({hole_center.x:.3f},{hole_center.y:.3f},{hole_center.z:.3f}) circEdges={n_circ_dbg} score={best_score:.3f}"
        )

    # If the selected point is suspiciously close to a mounting hole in X/Z, force to global center X/Z.
    if mount_centers:
        min_d = min(_dist_xz(hole_center, mc) for mc in mount_centers)
        safe_clear = (mount_r if mount_r else 0) + (0.85 * mm_to_model) + (2.0 * mm_to_model)  # mount radius + hole radius + 2mm buffer
        if min_d < safe_clear:
            print(
                f"WARNING: pocket-derived hole center too close to mounting pattern (min XZ dist {min_d:.3f} < {safe_clear:.3f}); moving hole to global mid X/Z."
            )
            hole_center = cq.Vector(midx, hole_center.y, midz)

    result = shape

    # ---------------- Operation 1: connecting hole Ø1.7mm (through all) ----------------
    hole_d = 1.7 * mm_to_model
    hole_r = hole_d / 2.0
    cut_len = max(3.0 * t_len, 4.0 * diag)

    # Start slightly towards bottom so the cut definitely opens into the pocket void
    base_p = hole_center - thickness_axis * (0.3 * mm_to_model)
    hole_cyl = cq.Solid.makeCylinder(hole_r, cut_len, base_p, thickness_axis)
    result = result.cut(hole_cyl)
    print(f"Connecting hole cut: diameter={hole_d:.4f} at ({hole_center.x:.3f},{hole_center.y:.3f},{hole_center.z:.3f})")

    # ---------------- Operation 2: grooves 0.1mm deep/0.1mm wide (3 rings per hole) ----------------
    if mount_r is None or len(mount_centers) != 4 or bottom_face is None:
        print("WARNING: mounting holes not reliably detected; grooves skipped.")
        return cq.Workplane("XY").newObject([result])

    groove_depth = 0.1 * mm_to_model
    groove_w = 0.1 * mm_to_model
    rings_per_hole = 3
    start_offset = 0.3 * mm_to_model
    pitch = 0.2 * mm_to_model

    groove_solids = []
    for c in mount_centers:
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
