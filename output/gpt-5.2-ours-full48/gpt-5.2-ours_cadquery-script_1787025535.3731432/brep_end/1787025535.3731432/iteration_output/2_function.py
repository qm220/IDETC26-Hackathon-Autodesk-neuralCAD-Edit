def my_cad_function(args):
    import cadquery as cq
    import os
    from math import sqrt

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
        return [p.x, p.y, p.z][idx]

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
        """Return (radius, center_point, axis_dir_unit) for circular edges else None."""
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
            return r, c, v
        except Exception:
            return None

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
        # find farthest pair
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
            # choose point maximizing min distance to chosen
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
    print(f"BBOX lens: x={xlen:.3f} y={ylen:.3f} z={zlen:.3f} diag={diag:.3f}")

    # Thickness axis = smallest bbox dimension
    lens = [(xlen, 0), (ylen, 1), (zlen, 2)]
    t_idx = sorted(lens, key=lambda a: a[0])[0][1]
    thickness_axis = [cq.Vector(1, 0, 0), cq.Vector(0, 1, 0), cq.Vector(0, 0, 1)][t_idx]
    thickness_axis = _unit(thickness_axis)
    print(f"Thickness axis index={t_idx} vec=({thickness_axis.x:.1f},{thickness_axis.y:.1f},{thickness_axis.z:.1f})")

    # Bottom plane coordinate (min along thickness axis)
    min_coord = [bbox.xmin, bbox.ymin, bbox.zmin][t_idx]
    max_coord = [bbox.xmax, bbox.ymax, bbox.zmax][t_idx]
    t_len = [xlen, ylen, zlen][t_idx]
    print(f"Thickness min={min_coord:.4f} max={max_coord:.4f} len={t_len:.4f}")

    # ---------------- Infer mounting holes from bottom circular edges ----------------
    # Find circular edges that lie on the bottom plane and whose circle axis is aligned with thickness axis.
    edges = list(shape.Edges())
    eps_plane = max(1e-4, 0.002 * max(xlen, ylen, zlen))

    bottom_circles = []  # (r, center)
    for e in edges:
        cd = _circle_edge_data(e)
        if cd is None:
            continue
        r, c, ax = cd
        if abs(_dot(ax, thickness_axis)) < 0.98:
            continue
        bb = e.BoundingBox()
        emin = [bb.xmin, bb.ymin, bb.zmin][t_idx]
        emax = [bb.xmax, bb.ymax, bb.zmax][t_idx]
        if abs(emin - min_coord) > eps_plane or abs(emax - min_coord) > eps_plane:
            continue
        # circle must be on the bottom plane
        bottom_circles.append((r, c))

    # Dedup by center (STEP often splits circles)
    bottom_circles = _unique_by_center(bottom_circles, tol=max(1e-3, 0.01 * eps_plane + 0.001))
    print(f"Bottom-plane circle candidates (deduped): {len(bottom_circles)}")
    if bottom_circles:
        rs = sorted([r for r, _ in bottom_circles])
        print(f"  radius range: {rs[0]:.4f} .. {rs[-1]:.4f}")

    # Cluster by radius and choose a cluster with >=4 circles and the largest nominal radius.
    # This should correspond to the 4 mounting holes.
    bottom_circles_sorted = sorted(bottom_circles, key=lambda t: t[0])
    clusters = []  # list of dict(r_nom, items)
    for r, c in bottom_circles_sorted:
        placed = False
        for cl in clusters:
            rnom = cl["r"]
            tol = 0.03 * max(r, rnom)  # 3% radius tolerance
            if abs(r - rnom) <= tol:
                cl["items"].append((r, c))
                cl["r"] = sum(rr for rr, _ in cl["items"]) / len(cl["items"])
                placed = True
                break
        if not placed:
            clusters.append({"r": r, "items": [(r, c)]})

    clusters = [cl for cl in clusters if len(cl["items"]) >= 4]
    clusters.sort(key=lambda cl: cl["r"], reverse=True)

    if not clusters:
        print("WARNING: Could not find a 4x radius cluster on the bottom plane for mounting holes; grooves will be skipped.")
        mount_centers = []
        mount_r = None
    else:
        cl = clusters[0]
        mount_r = cl["r"]
        pts = [c for _, c in cl["items"]]
        pts = _pick_4_spread(pts)
        mount_centers = pts
        print(f"Mount-hole cluster chosen: r~{mount_r:.4f} count={len(cl['items'])}; using centers={len(mount_centers)}")
        for i, c in enumerate(mount_centers):
            print(f"  mount_center[{i}] = ({c.x:.3f},{c.y:.3f},{c.z:.3f})")

    # ---------------- Unit scaling heuristic ----------------
    # Fusion STEP is often cm. If overall size ~ 5..100 and a mount hole radius looks < ~2.5, assume cm.
    maxdim = max(xlen, ylen, zlen)
    if mount_r is not None and 5 < maxdim < 100 and mount_r < 2.5:
        mm_to_model = 0.1
        unit_note = "Assuming model units are cm (Fusion STEP); 1 mm = 0.1 model units"
    else:
        mm_to_model = 1.0
        unit_note = "Assuming model units are mm; 1 mm = 1.0 model units"
    print(unit_note)

    # ---------------- Find underside pocket floor planar face ----------------
    # Look for planar faces aligned with thickness axis, not at bottom plane, and not near the top extreme.
    faces = list(shape.Faces())
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
        # exclude bottom-most plane faces
        if abs(cth - min_coord) <= max(eps_plane, 0.02 * t_len):
            continue
        # keep in the lower/middle portion of thickness to avoid any top-side spotfaces
        if cth > (min_coord + 0.75 * t_len):
            continue
        a = f.Area()
        if a > pocket_floor_area:
            pocket_floor_area = a
            pocket_floor_face = f

    if pocket_floor_face is None:
        # Fallback: just use bbox center projected to a mid plane above bottom
        hole_center = cq.Vector((bbox.xmin + bbox.xmax) / 2.0,
                                (bbox.ymin + bbox.ymax) / 2.0,
                                (bbox.zmin + bbox.zmax) / 2.0)
        print("WARNING: pocket floor face not found; using bbox center for connecting hole.")
    else:
        hc = pocket_floor_face.Center()
        hole_center = cq.Vector(hc.x, hc.y, hc.z)
        print(f"Pocket floor face picked: area={pocket_floor_area:.3f} center=({hole_center.x:.3f},{hole_center.y:.3f},{hole_center.z:.3f})")

    # ---------------- Operation 1: connecting hole Ø1.7mm (from pocket floor to exterior) ----------------
    hole_d = 1.7 * mm_to_model
    hole_r = hole_d / 2.0
    # Cut only upward from pocket floor toward +thickness direction so we do not punch through the bottom contact plane.
    cut_len = max(4.0 * diag, 200.0 * mm_to_model)
    base_p = hole_center - thickness_axis * (0.02 * mm_to_model)  # tiny offset to ensure intersection
    hole_cyl = cq.Solid.makeCylinder(hole_r, cut_len, base_p, thickness_axis)

    result = shape.cut(hole_cyl)
    print(f"Connecting hole cut: diameter={hole_d:.4f} at ({hole_center.x:.3f},{hole_center.y:.3f},{hole_center.z:.3f})")

    # ---------------- Operation 2: grooves 0.1mm deep/0.1mm wide, 3 rings per mounting hole ----------------
    groove_depth = 0.1 * mm_to_model
    groove_w = 0.1 * mm_to_model
    rings_per_hole = 3
    start_offset = 0.3 * mm_to_model
    pitch = 0.2 * mm_to_model

    if mount_r is None or len(mount_centers) != 4:
        print("WARNING: mounting holes not reliably detected; skipping grooves.")
        return cq.Workplane("XY").newObject([result])

    groove_solids = []
    # Groove direction into the part from the bottom contact plane is +thickness axis
    for c in mount_centers:
        for i in range(rings_per_hole):
            inner_r = mount_r + start_offset + i * pitch
            outer_r = inner_r + groove_w
            outer = cq.Solid.makeCylinder(outer_r, groove_depth, c, thickness_axis)
            inner = cq.Solid.makeCylinder(inner_r, groove_depth, c, thickness_axis)
            groove_solids.append(outer.cut(inner))

    g = groove_solids[0]
    for s in groove_solids[1:]:
        g = g.fuse(s)

    result = result.cut(g)
    print(f"Grooves cut: depth={groove_depth:.4f} width={groove_w:.4f} rings={len(groove_solids)}")

    print("Edit complete (connecting hole + grooves).")
    return cq.Workplane("XY").newObject([result])
