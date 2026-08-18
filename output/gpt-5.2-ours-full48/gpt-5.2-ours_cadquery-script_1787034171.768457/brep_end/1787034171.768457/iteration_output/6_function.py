def my_cad_function(args):
    import cadquery as cq
    import cadquery.selectors as cqs
    import os, math

    if "input_file" not in args:
        raise ValueError("Missing args['input_file']")

    input_file = os.path.expanduser(args["input_file"])
    wp_in = cq.importers.importStep(input_file)
    solid = wp_in.val()

    try:
        solid = cq.Workplane(obj=solid).combineSolids().val()
    except Exception:
        pass

    print(f"[DBG] Imported shape type: {type(solid)}")

    # -----------------------------
    # 1) Scale uniformly 10x about origin
    # -----------------------------
    if hasattr(solid, "scale"):
        solid = solid.scale(10.0)
    else:
        raise RuntimeError("Loaded shape does not support .scale()")

    bb = solid.BoundingBox()
    print(f"[DBG] After scale bbox: x=({bb.xmin:.3f},{bb.xmax:.3f}) y=({bb.ymin:.3f},{bb.ymax:.3f}) z=({bb.zmin:.3f},{bb.zmax:.3f})")

    def is_edge_on_bottom(edge_shape, bottom_z, tol=1e-3):
        ebb = edge_shape.BoundingBox()
        return abs(ebb.zmin - bottom_z) < tol and abs(ebb.zmax - bottom_z) < tol

    # -----------------------------
    # 5) Two cylindrical features (OD=6, ID=3), spaced 30mm along Y, centered
    # Start at bottom Z-level and go up to the top surface at that XY (saddle)
    # -----------------------------
    bb = solid.BoundingBox()
    bottom_z = bb.zmin

    pts = [(0.0, 15.0), (0.0, -15.0)]
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
    z_lo = bb.zmin - 200.0
    z_hi = bb.zmax + 200.0
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

    try:
        solid = cq.Workplane(obj=solid).combineSolids().val()
    except Exception:
        pass

    # -----------------------------
    # 2) Draft 2 degrees to all vertical-ish faces, hinge = bottom plane
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
    # 3 & 4) Fillets:
    # - Inner edges R=1mm, outer edges R=3mm
    # - Exclude ANY edges lying on the flat bottom surface (z=zmin)
    # Classification here follows the planning intent:
    #   outer = edges where both adjacent faces are on the outer envelope
    #   inner = remaining SHARP edges (pocket/hole/internal features)
    # Additionally, we only target SHARP edges (skip tangent/smooth edges)
    # to avoid fillet failures.
    # -----------------------------

    def clamp(v, lo, hi):
        return max(lo, min(hi, v))

    def build_face_maps(s):
        """Return (face_by_hash, face_is_exterior_by_hash) using CQ faces."""
        gbb = s.BoundingBox()
        xmin, xmax = gbb.xmin, gbb.xmax
        ymin, ymax = gbb.ymin, gbb.ymax
        zmin, zmax = gbb.zmin, gbb.zmax
        diag = math.sqrt((xmax - xmin) ** 2 + (ymax - ymin) ** 2 + (zmax - zmin) ** 2)
        tol_env = max(0.2, 0.002 * diag)  # mm-ish tolerance

        face_by_hash = {}
        face_ext = {}
        for f in s.Faces():
            try:
                h = f.wrapped.HashCode(2147483647)
            except Exception:
                continue
            face_by_hash[h] = f
            bb = f.BoundingBox()
            is_ext = (
                abs(bb.xmin - xmin) < tol_env or abs(bb.xmax - xmax) < tol_env or
                abs(bb.ymin - ymin) < tol_env or abs(bb.ymax - ymax) < tol_env or
                abs(bb.zmin - zmin) < tol_env or abs(bb.zmax - zmax) < tol_env
            )
            face_ext[h] = is_ext

        print(f"[DBG] Face maps: faces={len(face_by_hash)} tol_env={tol_env:.3f}")
        return face_by_hash, face_ext

    def collect_edge_points_by_outer_inner_sharp(s):
        try:
            from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
            from OCP.TopExp import TopExp_Explorer, TopExp
            from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape
            from OCP.TopoDS import TopoDS
        except Exception as e:
            print(f"[DBG] WARN: OCP adjacency unavailable; skipping fillets. Error: {e}")
            return [], []

        def as_edge(sh):
            if hasattr(TopoDS, "Edge_s"):
                return TopoDS.Edge_s(sh)
            if hasattr(TopoDS, "Edge"):
                return TopoDS.Edge(sh)
            return sh

        def as_face(sh):
            if hasattr(TopoDS, "Face_s"):
                return TopoDS.Face_s(sh)
            if hasattr(TopoDS, "Face"):
                return TopoDS.Face(sh)
            return sh

        bb = s.BoundingBox()
        bottom_z = bb.zmin

        face_by_hash, face_ext = build_face_maps(s)

        amap = TopTools_IndexedDataMapOfShapeListOfShape()
        if hasattr(TopExp, "MapShapesAndAncestors_s"):
            TopExp.MapShapesAndAncestors_s(s.wrapped, TopAbs_EDGE, TopAbs_FACE, amap)
        else:
            TopExp.MapShapesAndAncestors(s.wrapped, TopAbs_EDGE, TopAbs_FACE, amap)

        outer_pts = []
        inner_pts = []

        eexp = TopExp_Explorer(s.wrapped, TopAbs_EDGE)
        total = two_face = skipped_bottom = skipped_smooth = 0
        while eexp.More():
            total += 1
            ew = as_edge(eexp.Current())

            # exclude edges on flat bottom
            try:
                ebb = cq.Shape.cast(ew).BoundingBox()
                if abs(ebb.zmin - bottom_z) < 1e-3 and abs(ebb.zmax - bottom_z) < 1e-3:
                    skipped_bottom += 1
                    eexp.Next()
                    continue
            except Exception:
                pass

            if not amap.Contains(ew):
                eexp.Next()
                continue

            faces_list = amap.FindFromKey(ew)
            if faces_list.Extent() != 2:
                eexp.Next()
                continue

            two_face += 1
            f1w = as_face(faces_list.First())
            f2w = as_face(faces_list.Last())

            try:
                h1 = f1w.HashCode(2147483647)
                h2 = f2w.HashCode(2147483647)
            except Exception:
                eexp.Next()
                continue

            f1 = face_by_hash.get(h1, None)
            f2 = face_by_hash.get(h2, None)
            if f1 is None or f2 is None:
                eexp.Next()
                continue

            ext1 = face_ext.get(h1, False)
            ext2 = face_ext.get(h2, False)

            # sharpness test: compare normals of adjacent faces at edge midpoint
            try:
                p = cq.Shape.cast(ew).Center()
            except Exception:
                eexp.Next()
                continue

            try:
                (u1, v1) = f1.paramAt(p)
                (u2, v2) = f2.paramAt(p)
                n1 = f1.normalAt(u1, v1)
                n2 = f2.normalAt(u2, v2)
                dot = clamp(n1.dot(n2), -1.0, 1.0)
                ang = math.acos(dot)
                if ang < math.radians(3.0):
                    skipped_smooth += 1
                    eexp.Next()
                    continue
            except Exception:
                # If we can't evaluate normals, skip to avoid fillet failures
                eexp.Next()
                continue

            if ext1 and ext2:
                outer_pts.append((p.x, p.y, p.z))
            else:
                inner_pts.append((p.x, p.y, p.z))

            eexp.Next()

        print(
            f"[DBG] Edge scan: total={total} two_face={two_face} "
            f"skipped_bottom={skipped_bottom} skipped_smooth={skipped_smooth} "
            f"outer_sharp={len(outer_pts)} inner_sharp={len(inner_pts)}"
        )
        return outer_pts, inner_pts

    def dedup_xyz(pts, nd=2):
        seen = set()
        out = []
        for (x, y, z) in pts:
            k = (round(x, nd), round(y, nd), round(z, nd))
            if k in seen:
                continue
            seen.add(k)
            out.append((x, y, z))
        return out

    def fillet_points_one_by_one(s, pts, radius, label, pick_tol=10.0):
        done = fail = skipped = 0
        bottom_z_local = s.BoundingBox().zmin
        for (x, y, z) in pts:
            try:
                sel = cqs.NearestToPointSelector((x, y, z))
                e = cq.Workplane(obj=s).edges(sel).val()

                if is_edge_on_bottom(e, bottom_z_local, tol=1e-3):
                    skipped += 1
                    continue

                try:
                    em = e.Center()
                    dist = math.sqrt((em.x - x) ** 2 + (em.y - y) ** 2 + (em.z - z) ** 2)
                    if dist > pick_tol:
                        skipped += 1
                        continue
                except Exception:
                    pass

                s = cq.Workplane(obj=s).edges(sel).fillet(radius).val()
                done += 1
            except Exception:
                fail += 1

        print(f"[DBG] Fillet {label}: targets={len(pts)} success={done} fail={fail} skipped={skipped}")
        return s

    bb = solid.BoundingBox()
    print(f"[DBG] Pre-fillet bbox: x=({bb.xmin:.3f},{bb.xmax:.3f}) y=({bb.ymin:.3f},{bb.ymax:.3f}) z=({bb.zmin:.3f},{bb.zmax:.3f})")

    # Outer fillets first (R=3)
    outer_pts, _ = collect_edge_points_by_outer_inner_sharp(solid)
    outer_pts = dedup_xyz(outer_pts, nd=2)
    outer_pts = sorted(outer_pts, key=lambda p: (-p[2], -abs(p[0]) - abs(p[1])))
    print(f"[DBG] Outer sharp edge targets (dedup): {len(outer_pts)}")
    solid = fillet_points_one_by_one(solid, outer_pts, 3.0, "outer R3", pick_tol=12.0)

    # Recompute inner after outer fillets (topology changes)
    _, inner_pts = collect_edge_points_by_outer_inner_sharp(solid)
    inner_pts = dedup_xyz(inner_pts, nd=2)
    inner_pts = sorted(inner_pts, key=lambda p: (-p[2], abs(p[0]) + abs(p[1])))
    print(f"[DBG] Inner sharp edge targets (dedup): {len(inner_pts)}")
    solid = fillet_points_one_by_one(solid, inner_pts, 1.0, "inner R1", pick_tol=10.0)

    try:
        solid = cq.Workplane(obj=solid).combineSolids().val()
    except Exception:
        pass

    bb_end = solid.BoundingBox()
    print(f"[DBG] End bbox: x=({bb_end.xmin:.3f},{bb_end.xmax:.3f}) y=({bb_end.ymin:.3f},{bb_end.ymax:.3f}) z=({bb_end.zmin:.3f},{bb_end.zmax:.3f})")

    return cq.Workplane(obj=solid)
