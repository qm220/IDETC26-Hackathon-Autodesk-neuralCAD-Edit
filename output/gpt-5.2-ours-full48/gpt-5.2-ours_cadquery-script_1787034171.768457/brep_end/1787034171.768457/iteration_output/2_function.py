def my_cad_function(args):
    import cadquery as cq
    import cadquery.selectors as cqs
    import os, math

    if "input_file" not in args:
        raise ValueError("Missing args['input_file']")

    input_file = os.path.expanduser(args["input_file"])
    wp_in = cq.importers.importStep(input_file)
    shp_in = wp_in.val()

    # Ensure single solid when possible
    try:
        shp_in = cq.Workplane(obj=shp_in).combineSolids().val()
    except Exception:
        pass

    if not isinstance(shp_in, cq.Solid):
        # best effort
        try:
            shp_in = cq.Workplane(obj=shp_in).combineSolids().val()
        except Exception:
            pass

    print(f"[DBG] Imported shape type: {type(shp_in)}")

    # -----------------------------
    # 1) Scale uniformly 10x about origin
    # -----------------------------
    solid = shp_in.scale(10.0) if hasattr(shp_in, "scale") else shp_in

    bb = solid.BoundingBox()
    print(f"[DBG] After scale bbox: x=({bb.xmin:.3f},{bb.xmax:.3f}) y=({bb.ymin:.3f},{bb.ymax:.3f}) z=({bb.zmin:.3f},{bb.zmax:.3f})")

    bottom_z = bb.zmin

    # Helpers
    def edge_on_bottom(e, zref, tol=1e-3):
        ebb = e.BoundingBox()
        return abs(ebb.zmin - zref) < tol and abs(ebb.zmax - zref) < tol

    def v_mid_edge(e):
        try:
            c = e.Center()
            return cq.Vector(c.x, c.y, c.z)
        except Exception:
            ebb = e.BoundingBox()
            return cq.Vector((ebb.xmin + ebb.xmax) / 2.0, (ebb.ymin + ebb.ymax) / 2.0, (ebb.zmin + ebb.zmax) / 2.0)

    # -----------------------------
    # 5) Add two cylindrical features (OD=6, ID=3), spaced 30mm, centered
    # -----------------------------
    pts = [(0.0, 15.0), (0.0, -15.0)]  # along Y, symmetric
    boss_r = 3.0
    hole_r = 1.5

    def top_z_at_xy(s, x, y, z_lo, z_hi):
        line = cq.Edge.makeLine(cq.Vector(x, y, z_lo), cq.Vector(x, y, z_hi))
        try:
            common = s.intersect(line)
            cbb = common.BoundingBox()
            if (cbb.zmax - cbb.zmin) < 1e-7:
                return None
            return cbb.zmax
        except Exception:
            return None

    bb = solid.BoundingBox()
    z_lo = bb.zmin - 5.0
    z_hi = bb.zmax + 5.0

    base_plane = cq.Plane(origin=(0, 0, bottom_z), normal=(0, 0, 1), xDir=(1, 0, 0))

    for (x, y) in pts:
        zt = top_z_at_xy(solid, x, y, z_lo, z_hi)
        if zt is None:
            zt = bb.zmax
            print(f"[DBG] WARN: Could not ray-intersect top at ({x},{y}); using top_z={zt:.3f}")
        height = max(0.1, zt - bottom_z)

        boss = cq.Workplane(base_plane).center(x, y).circle(boss_r).extrude(height).val()
        solid = solid.fuse(boss)

        hole = cq.Workplane(base_plane).center(x, y).circle(hole_r).extrude(height).val()
        solid = solid.cut(hole)

        print(f"[DBG] Boss at ({x:.1f},{y:.1f}) height={height:.3f} (bottom_z={bottom_z:.3f} -> z_top={zt:.3f})")

    # -----------------------------
    # 2) Draft 2 degrees to ALL vertical surfaces, hinge = flat bottom plane
    # Implemented via OCCT BRepOffsetAPI_DraftAngle (CQ Workplane has no .draft() here)
    # -----------------------------
    def apply_draft_occ(s, angle_deg=2.0):
        try:
            from OCP.BRepOffsetAPI import BRepOffsetAPI_DraftAngle
            from OCP.gp import gp_Dir, gp_Pln, gp_Pnt
        except Exception as e:
            print(f"[DBG] WARN: OCP draft imports failed; skipping draft. Error: {e}")
            return s

        bb_local = s.BoundingBox()
        zmin = bb_local.zmin

        pull_dir = gp_Dir(0, 0, 1)
        neutral = gp_Pln(gp_Pnt(0, 0, zmin), gp_Dir(0, 0, 1))

        # select vertical-ish faces by normal at center
        vert_faces = []
        for f in s.Faces():
            try:
                n = f.normalAt(f.Center())
            except Exception:
                continue
            if abs(n.z) < 0.2:
                vert_faces.append(f)

        print(f"[DBG] Draft vertical-face candidates: {len(vert_faces)}")
        if not vert_faces:
            return s

        ang = math.radians(angle_deg)

        def _do(angle_rad):
            da = BRepOffsetAPI_DraftAngle(s.wrapped)
            for ff in vert_faces:
                da.Add(ff.wrapped, pull_dir, angle_rad, neutral)
            da.Build()
            try:
                done = da.IsDone()
            except Exception:
                done = True
            if not done:
                return None
            out = cq.Shape.cast(da.Shape())
            try:
                out = cq.Workplane(obj=out).combineSolids().val()
            except Exception:
                pass
            return out

        out = _do(ang)
        if out is None:
            print("[DBG] WARN: Draft (+) failed; trying negative angle")
            out = _do(-ang)

        if out is None:
            print("[DBG] WARN: Draft failed both signs; continuing without draft")
            return s

        print("[DBG] Draft applied")
        return out

    solid = apply_draft_occ(solid, 2.0)

    # -----------------------------
    # 3 & 4) Fillets: inner R=1, outer R=3; exclude edges on flat bottom plane
    # Use point-driven per-edge filleting via NearestToPointSelector to avoid global failure
    # -----------------------------
    bb = solid.BoundingBox()
    zmin = bb.zmin
    zmax = bb.zmax
    xmax = max(abs(bb.xmin), abs(bb.xmax))
    ymax = max(abs(bb.ymin), abs(bb.ymax))

    # Collect sharp edge midpoints and classify outer vs inner by position.
    # Also skip near-tangent edges (already smooth) by checking face-normal angle.
    # NOTE: face adjacency is not directly exposed cleanly; we approximate sharpness via
    #       trying to infer from edge type/length and leaving selection conservative.

    tol_xy = 0.65
    tol_top = 1.2
    min_len = 0.25

    # Precompute candidate points from current topology
    outer_pts = []
    inner_pts = []

    for e in solid.Edges():
        if edge_on_bottom(e, zmin, tol=1e-3):
            continue
        try:
            if e.Length() < min_len:
                continue
        except Exception:
            pass

        m = v_mid_edge(e)

        is_outer = (abs(m.x) > (xmax - tol_xy)) or (abs(m.y) > (ymax - tol_xy)) or (m.z > (zmax - tol_top))
        # Prefer to keep bosses/holes as inner features unless clearly exterior
        if is_outer:
            outer_pts.append((m.x, m.y, m.z))
        else:
            inner_pts.append((m.x, m.y, m.z))

    print(f"[DBG] Candidate edge points (excluding bottom): outer={len(outer_pts)} inner={len(inner_pts)}")

    def fillet_by_points(s, pts_list, radius, label, max_ops=500, pick_tol=2.5):
        done = 0
        fail = 0
        for i, pt in enumerate(pts_list[:max_ops]):
            # skip points too close to bottom plane (safety)
            if abs(pt[2] - s.BoundingBox().zmin) < 1e-3:
                continue
            try:
                # identify the nearest edge
                wp = cq.Workplane(obj=s)
                sel = cqs.NearestToPointSelector(pt)
                # get the selected edge and validate it's not bottom
                e = wp.edges(sel).val()
                if edge_on_bottom(e, s.BoundingBox().zmin, tol=1e-3):
                    continue

                # Ensure selection point is still near the edge (avoid snapping to unrelated edges)
                try:
                    em = v_mid_edge(e)
                    d = math.sqrt((em.x - pt[0]) ** 2 + (em.y - pt[1]) ** 2 + (em.z - pt[2]) ** 2)
                    if d > pick_tol:
                        continue
                except Exception:
                    pass

                s = cq.Workplane(obj=s).edges(sel).fillet(radius).val()
                done += 1
            except Exception:
                fail += 1
                continue

        print(f"[DBG] Fillet {label}: attempted={min(len(pts_list), max_ops)} success={done} fail={fail}")
        return s

    # 4) Outer fillets R=3 (exclude bottom by construction)
    # Sort points for stability: start with highest Z then extremes
    outer_pts_sorted = sorted(outer_pts, key=lambda p: (-p[2], -abs(p[0]) - abs(p[1])))
    solid = fillet_by_points(solid, outer_pts_sorted, 3.0, "outer R3", max_ops=400, pick_tol=3.0)

    # 3) Inner fillets R=1
    # Sort: prioritize larger Z (pocket ceiling) then interior
    inner_pts_sorted = sorted(inner_pts, key=lambda p: (-p[2], abs(p[0]) + abs(p[1])))
    solid = fillet_by_points(solid, inner_pts_sorted, 1.0, "inner R1", max_ops=800, pick_tol=2.5)

    bb_end = solid.BoundingBox()
    print(f"[DBG] End bbox: x=({bb_end.xmin:.3f},{bb_end.xmax:.3f}) y=({bb_end.ymin:.3f},{bb_end.ymax:.3f}) z=({bb_end.zmin:.3f},{bb_end.zmax:.3f})")

    return cq.Workplane(obj=solid)
