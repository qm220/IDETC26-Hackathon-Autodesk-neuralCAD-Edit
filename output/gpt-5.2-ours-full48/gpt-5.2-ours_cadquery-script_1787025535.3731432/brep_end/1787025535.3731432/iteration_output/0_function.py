def my_cad_function(args):
    import cadquery as cq
    import os
    from math import sqrt

    # --- Helpers (OCP-based for robust geometry interrogation) ---
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

    def _face_plane_normal(face: cq.Face):
        # Returns (point_on_plane, unit_normal) for planar faces; else (None, None)
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

    def _cyl_face_data(face: cq.Face):
        # Returns (radius, axis_point, axis_dir_unit) for cylindrical faces; else None
        try:
            from OCP.BRepAdaptor import BRepAdaptor_Surface
            from OCP.GeomAbs import GeomAbs_Cylinder

            ad = BRepAdaptor_Surface(face.wrapped)
            if ad.GetType() != GeomAbs_Cylinder:
                return None
            cyl = ad.Cylinder()
            r = cyl.Radius()
            ax = cyl.Axis()
            loc = ax.Location()
            d = ax.Direction()
            p = cq.Vector(loc.X(), loc.Y(), loc.Z())
            v = _unit(cq.Vector(d.X(), d.Y(), d.Z()))
            return float(r), p, v
        except Exception:
            return None

    # --- Load STEP ---
    if "input_file" not in args:
        raise ValueError("Expected args['input_file'] for edit operation")
    input_file = os.path.expanduser(args["input_file"])
    wp = cq.importers.importStep(input_file)
    shape = wp.val() if hasattr(wp, "val") else wp

    if not shape.isValid():
        print("WARNING: imported shape is not valid according to OCC")

    bbox = shape.BoundingBox()
    xlen, ylen, zlen = bbox.xlen, bbox.ylen, bbox.zlen
    print(f"BBOX lens: x={xlen:.3f} y={ylen:.3f} z={zlen:.3f}")

    # Thickness axis = smallest bbox dimension (assumption: mounting holes are along this axis)
    lens = [(xlen, 0), (ylen, 1), (zlen, 2)]
    t_idx = sorted(lens, key=lambda a: a[0])[0][1]
    thickness_axis = [cq.Vector(1, 0, 0), cq.Vector(0, 1, 0), cq.Vector(0, 0, 1)][t_idx]
    print(f"Thickness axis index={t_idx} vec=({thickness_axis.x},{thickness_axis.y},{thickness_axis.z})")

    def _coord_on_axis(p: cq.Vector, axis_idx: int) -> float:
        return [p.x, p.y, p.z][axis_idx]

    # --- Identify bottom base planar face (large planar face with normal ~ thickness axis and lowest coord) ---
    faces = list(shape.Faces())
    planar_candidates = []
    for f in faces:
        p0, n = _face_plane_normal(f)
        if p0 is None:
            continue
        # normals near +/- thickness axis
        if abs(_dot(n, thickness_axis)) < 0.95:
            continue
        c = f.Center()
        planar_candidates.append((f, f.Area(), cq.Vector(c.x, c.y, c.z), n))

    if not planar_candidates:
        raise RuntimeError("Could not find planar faces aligned to thickness axis")

    planar_candidates.sort(key=lambda t: (_coord_on_axis(t[2], t_idx), -t[1]))
    bottom_face, bottom_area, bottom_center, bottom_n = planar_candidates[0]
    print(f"Bottom face area={bottom_area:.2f} center=({bottom_center.x:.2f},{bottom_center.y:.2f},{bottom_center.z:.2f}) normal=({bottom_n.x:.3f},{bottom_n.y:.3f},{bottom_n.z:.3f})")

    # --- Identify underside pocket floor planar face (parallel to bottom, above it, sizable) ---
    # Expect pocket floor to be offset from bottom along thickness axis.
    pocket_floor = None
    pocket_floor_score = None
    for f, area, ctr, n in planar_candidates[1:]:
        # same plane normal direction as bottom or opposite is okay; pocket floor is usually internal so might match bottom
        if abs(_dot(n, bottom_n)) < 0.98:
            continue
        d = _coord_on_axis(ctr, t_idx) - _coord_on_axis(bottom_center, t_idx)
        if d < 0.5:  # must be above the bottom plane by at least 0.5 mm
            continue
        if area > bottom_area * 0.95:
            continue
        # Prefer larger area and moderate offset
        score = area
        if (pocket_floor is None) or (score > pocket_floor_score):
            pocket_floor = f
            pocket_floor_score = score

    if pocket_floor is None:
        print("WARNING: Could not confidently identify pocket floor face; will fall back to second-lowest planar face.")
        pocket_floor = planar_candidates[1][0]

    pf_c = pocket_floor.Center()
    pocket_center = cq.Vector(pf_c.x, pf_c.y, pf_c.z)
    print(f"Pocket floor center=({pocket_center.x:.2f},{pocket_center.y:.2f},{pocket_center.z:.2f}) area={pocket_floor.Area():.2f}")

    # --- Find 4 mounting-hole centers (use cylindrical faces with axis ~ thickness axis; choose smallest-radius group with >=4 uniques) ---
    cyls = []
    for f in faces:
        data = _cyl_face_data(f)
        if data is None:
            continue
        r, ap, av = data
        if abs(_dot(av, thickness_axis)) < 0.98:
            continue
        # Ignore extremely small / huge cylinders
        if r < 0.3 or r > 20:
            continue
        cyls.append((r, ap, av))

    print(f"Cyl faces aligned to thickness axis: {len(cyls)}")

    # Cluster by radius
    cyls.sort(key=lambda t: t[0])
    radius_groups = []  # list of (r_nom, items)
    rtol = 0.15
    for item in cyls:
        r = item[0]
        placed = False
        for i, (rn, items) in enumerate(radius_groups):
            if abs(r - rn) <= rtol:
                items.append(item)
                # update nominal
                radius_groups[i] = ((rn * (len(items) - 1) + r) / len(items), items)
                placed = True
                break
        if not placed:
            radius_groups.append((r, [item]))

    # Determine bottom plane (point and outward normal) for projection
    bp_p, bp_n = _face_plane_normal(bottom_face)
    if bp_p is None:
        bp_p = bottom_center
        bp_n = bottom_n

    def _project_to_plane(pt: cq.Vector, plane_p: cq.Vector, plane_n_unit: cq.Vector) -> cq.Vector:
        v = pt - plane_p
        dist = _dot(v, plane_n_unit)
        return pt - plane_n_unit * dist

    mounting_centers = []
    chosen_r = None
    for rn, items in radius_groups:
        # Build unique centers by clustering projected axis points
        centers = []
        for r, ap, av in items:
            pp = _project_to_plane(ap, bp_p, bp_n)
            if all(_dist(pp, c) > 0.8 for c in centers):
                centers.append(pp)
        if len(centers) >= 4:
            chosen_r = rn
            # take 4 that are farthest apart (simple: sort by x then take extremes; then fill)
            centers_sorted = sorted(centers, key=lambda v: (v.x, v.y, v.z))
            # keep first 4 distinct
            mounting_centers = []
            for c in centers_sorted:
                if all(_dist(c, e) > 0.8 for e in mounting_centers):
                    mounting_centers.append(c)
                if len(mounting_centers) == 4:
                    break
            break

    if len(mounting_centers) != 4:
        print("WARNING: Did not find 4 mounting hole centers reliably; found:", len(mounting_centers))
    else:
        print(f"Chosen mounting-hole small-bore radius ~ {chosen_r:.3f} mm")
        for i, c in enumerate(mounting_centers):
            print(f"  mount_center[{i}] = ({c.x:.3f},{c.y:.3f},{c.z:.3f})")

    # Define into-part direction from bottom face: into-part is opposite of outward normal
    into_part = _unit(bp_n * -1.0)

    # --- Operation 1: Add connecting hole Ø1.7 (through all), centered on pocket floor centroid ---
    # Create a long cylinder along thickness axis passing through pocket center.
    diag = sqrt(xlen * xlen + ylen * ylen + zlen * zlen)
    hole_len = max(5 * diag, 200.0)

    # Ensure drilling direction is aligned with thickness axis (not necessarily into_part)
    drill_dir = _unit(thickness_axis)
    # Base point far "below" the pocket center along -drill_dir so it spans through all
    base_p = pocket_center - drill_dir * hole_len
    hole_cyl = cq.Solid.makeCylinder(1.7 / 2.0, 2 * hole_len, base_p, drill_dir)

    result = shape.cut(hole_cyl)

    # --- Operation 2: Add 0.1mm deep grooves (3 rings per hole) on bottom base plane ---
    groove_depth = 0.1
    groove_w = 0.1
    rings_per_hole = 3
    start_offset = 0.3
    pitch = 0.2

    if chosen_r is None:
        # fallback guess if we couldn't infer mounting hole radius
        chosen_r = 2.0

    groove_solids = []
    for c in mounting_centers:
        # Base point on bottom plane
        c0 = _project_to_plane(c, bp_p, bp_n)
        for i in range(rings_per_hole):
            inner_r = chosen_r + start_offset + i * pitch
            outer_r = inner_r + groove_w
            outer = cq.Solid.makeCylinder(outer_r, groove_depth, c0, into_part)
            inner = cq.Solid.makeCylinder(inner_r, groove_depth, c0, into_part)
            ring = outer.cut(inner)
            groove_solids.append(ring)

    if groove_solids:
        grooves = groove_solids[0]
        for s in groove_solids[1:]:
            grooves = grooves.fuse(s)
        result = result.cut(grooves)
        print(f"Grooves created: {len(groove_solids)} rings (expected {len(mounting_centers) * rings_per_hole}).")
    else:
        print("WARNING: No groove solids created (mounting centers not found).")

    print("Edit complete (connecting hole + grooves).")
    return cq.Workplane("XY").newObject([result])
