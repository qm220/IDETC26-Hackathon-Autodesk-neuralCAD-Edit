def my_cad_function(args):
    import cadquery as cq
    import cadquery.selectors as cqs
    import os, math

    if "input_file" not in args:
        raise ValueError("Missing args['input_file']")

    input_file = os.path.expanduser(args["input_file"])
    wp_in = cq.importers.importStep(input_file)
    shp_in = wp_in.val()

    # Ensure single solid if possible
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

    def edge_on_bottom(e, zref, tol=1e-3):
        ebb = e.BoundingBox()
        return abs(ebb.zmin - zref) < tol and abs(ebb.zmax - zref) < tol

    # -----------------------------
    # 5) Add two cylindrical features (OD=6, ID=3), spaced 30mm, centered
    # Do before draft so draft applies to their vertical walls too.
    # -----------------------------
    bb = solid.BoundingBox()
    bottom_z = bb.zmin

    pts = [(0.0, 15.0), (0.0, -15.0)]  # 30mm spacing along Y
    boss_r = 3.0
    hole_r = 1.5

    def top_z_at_xy(s, x, y, z_lo, z_hi):
        # Intersect a vertical line with the solid; use highest z of intersection
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
    z_lo = bb.zmin - 50.0
    z_hi = bb.zmax + 50.0
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
            # normals mostly horizontal -> vertical faces
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
    #   - inner edges R=1mm
    #   - outer edges R=3mm
    #   - exclude any edges on the flat bottom surface (z=zmin)
    # Use OCP sharp-edge detection (dihedral angle) and classify by bbox proximity.
    # -----------------------------
    def compute_sharp_edge_midpoints(s, bottom_z, sharp_deg_threshold=175.0):
        try:
            from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_REVERSED
            from OCP.TopExp import TopExp_Explorer, TopExp
            from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape
            from OCP.TopoDS import TopoDS
            from OCP.BRep import BRep_Tool
            from OCP.BRepAdaptor import BRepAdaptor_Curve
            from OCP.GeomLProp import GeomLProp_SLProps
        except Exception as e:
            print(f"[DBG] WARN: OCP sharp-edge detection unavailable; cannot compute fillet target edges. Error: {e}")
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
        xmax = max(abs(bb.xmin), abs(bb.xmax))
        ymax = max(abs(bb.ymin), abs(bb.ymax))
        zmax = bb.zmax

        amap = TopTools_IndexedDataMapOfShapeListOfShape()
        TopExp.MapShapesAndAncestors(s.wrapped, TopAbs_EDGE, TopAbs_FACE, amap)

        outer_pts, inner_pts = [], []

        def _edge_midpoint(edge):
            c3d_handle, fpar, lpar = BRep_Tool.Curve(edge)
            if c3d_handle.IsNull():
                ac = BRepAdaptor_Curve(edge)
                fpar = ac.FirstParameter()
                lpar = ac.LastParameter()
                t = 0.5 * (fpar + lpar)
                p = ac.Value(t)
                return cq.Vector(p.X(), p.Y(), p.Z())
            c3d = c3d_handle.GetObject()
            t = 0.5 * (fpar + lpar)
            p = c3d.Value(t)
            return cq.Vector(p.X(), p.Y(), p.Z())

        def _edge_mid_param(edge):
            c3d_handle, fpar, lpar = BRep_Tool.Curve(edge)
            if not c3d_handle.IsNull():
                return 0.5 * (fpar + lpar)
            ac = BRepAdaptor_Curve(edge)
            return 0.5 * (ac.FirstParameter() + ac.LastParameter())

        def _face_normal_on_edge(face, edge, t_edge):
            try:
                h2d, surf_h, loc, f2, l2 = BRep_Tool.CurveOnSurface(edge, face)
            except Exception:
                # Some builds have different signature; give up on this edge
                return None
            if h2d.IsNull() or surf_h.IsNull():
                return None
            uv = h2d.GetObject().Value(t_edge)
            surf = surf_h.GetObject()
            props = GeomLProp_SLProps(surf, uv.X(), uv.Y(), 1, 1e-6)
            if not props.IsNormalDefined():
                return None
            n = props.Normal()
            try:
                n.Transform(loc.Transformation())
            except Exception:
                pass
            if face.Orientation() == TopAbs_REVERSED:
                n.Reverse()
            return cq.Vector(n.X(), n.Y(), n.Z())

        exp = TopExp_Explorer(s.wrapped, TopAbs_EDGE)
        cnt_total = cnt_sharp = cnt_skipped_bottom = cnt_norm_fail = 0

        while exp.More():
            cnt_total += 1
            ew = as_edge(exp.Current())

            # Exclude edges that lie on the bottom plane
            try:
                ebb = cq.Shape.cast(ew).BoundingBox()
                if abs(ebb.zmin - bottom_z) < 1e-3 and abs(ebb.zmax - bottom_z) < 1e-3:
                    cnt_skipped_bottom += 1
                    exp.Next()
                    continue
            except Exception:
                pass

            if not amap.Contains(ew):
                exp.Next()
                continue

            faces_list = amap.FindFromKey(ew)
            if faces_list.Extent() != 2:
                exp.Next()
                continue

            t = _edge_mid_param(ew)
            f1 = as_face(faces_list.First())
            f2 = as_face(faces_list.Last())

            n1 = _face_normal_on_edge(f1, ew, t)
            n2 = _face_normal_on_edge(f2, ew, t)
            if n1 is None or n2 is None:
                cnt_norm_fail += 1
                exp.Next()
                continue

            d = max(-1.0, min(1.0, (n1.normalized().dot(n2.normalized()))))
            ang = math.degrees(math.acos(d))

            # skip near-tangent edges
            if ang >= sharp_deg_threshold:
                exp.Next()
                continue

            cnt_sharp += 1
            mp = _edge_midpoint(ew)

            # Outer vs inner by proximity to envelope; keep thresholds high so pocket edges (x=0.8*Xmax, y=0.933*Ymax) stay inner
            is_outer = (abs(mp.x) > 0.97 * xmax) or (abs(mp.y) > 0.97 * ymax) or (mp.z > zmax - 1.0)
            if is_outer:
                outer_pts.append((mp.x, mp.y, mp.z, ang))
            else:
                inner_pts.append((mp.x, mp.y, mp.z, ang))

            exp.Next()

        print(f"[DBG] Sharp-edge scan: total_edges={cnt_total} sharp={cnt_sharp} skipped_bottom={cnt_skipped_bottom} normal_fail={cnt_norm_fail}")
        return outer_pts, inner_pts

    def dedup_pts(pts, nd=2):
        seen = set()
        out = []
        for (x, y, z, ang) in pts:
            k = (round(x, nd), round(y, nd), round(z, nd))
            if k in seen:
                continue
            seen.add(k)
            out.append((x, y, z, ang))
        return out

    def fillet_by_points_sequential(s, pts, radius, label, pick_tol=4.0, max_ops=5000):
        done = fail = skipped = 0
        for (x, y, z, ang) in pts[:max_ops]:
            try:
                sel = cqs.NearestToPointSelector((x, y, z))
                wp = cq.Workplane(obj=s)
                e = wp.edges(sel).val()
                if edge_on_bottom(e, s.BoundingBox().zmin, tol=1e-3):
                    skipped += 1
                    continue

                # sanity check: midpoint proximity
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

    outer_pts, inner_pts = compute_sharp_edge_midpoints(solid, bb.zmin, sharp_deg_threshold=175.0)
    outer_pts = dedup_pts(outer_pts, nd=2)
    inner_pts = dedup_pts(inner_pts, nd=2)

    outer_pts_sorted = sorted(outer_pts, key=lambda p: (-p[2], -abs(p[0]) - abs(p[1]), p[3]))
    inner_pts_sorted = sorted(inner_pts, key=lambda p: (-p[2], abs(p[0]) + abs(p[1]), p[3]))

    print(f"[DBG] Sharp edge targets (excl. bottom): outer={len(outer_pts_sorted)} inner={len(inner_pts_sorted)}")

    # 4) Outer fillets R=3mm
    solid = fillet_by_points_sequential(solid, outer_pts_sorted, 3.0, "outer R3", pick_tol=6.0)

    # 3) Inner fillets R=1mm
    solid = fillet_by_points_sequential(solid, inner_pts_sorted, 1.0, "inner R1", pick_tol=5.0)

    bb_end = solid.BoundingBox()
    print(f"[DBG] End bbox: x=({bb_end.xmin:.3f},{bb_end.xmax:.3f}) y=({bb_end.ymin:.3f},{bb_end.ymax:.3f}) z=({bb_end.zmin:.3f},{bb_end.zmax:.3f})")

    return cq.Workplane(obj=solid)
