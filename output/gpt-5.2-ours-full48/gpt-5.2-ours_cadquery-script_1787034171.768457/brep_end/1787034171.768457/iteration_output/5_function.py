def my_cad_function(args):
    import cadquery as cq
    import cadquery.selectors as cqs
    import os, math

    if "input_file" not in args:
        raise ValueError("Missing args['input_file']")

    input_file = os.path.expanduser(args["input_file"])
    wp_in = cq.importers.importStep(input_file)
    shp_in = wp_in.val()

    # Try to ensure single solid
    try:
        shp_in = cq.Workplane(obj=shp_in).combineSolids().val()
    except Exception:
        pass

    print(f"[DBG] Imported shape type: {type(shp_in)}")

    # -----------------------------
    # 1) Scale uniformly 10x about origin
    # -----------------------------
    if hasattr(shp_in, "scale"):
        solid = shp_in.scale(10.0)
    else:
        # fallback (should not happen)
        solid = shp_in

    bb = solid.BoundingBox()
    print(f"[DBG] After scale bbox: x=({bb.xmin:.3f},{bb.xmax:.3f}) y=({bb.ymin:.3f},{bb.ymax:.3f}) z=({bb.zmin:.3f},{bb.zmax:.3f})")

    def is_edge_on_bottom(edge_shape, bottom_z, tol=1e-3):
        ebb = edge_shape.BoundingBox()
        return abs(ebb.zmin - bottom_z) < tol and abs(ebb.zmax - bottom_z) < tol

    # -----------------------------
    # 5) Add two cylindrical features (OD=6, ID=3), spaced 30mm, centered
    # Do before draft so draft can affect their vertical walls too.
    # -----------------------------
    bb = solid.BoundingBox()
    bottom_z = bb.zmin

    pts = [(0.0, 15.0), (0.0, -15.0)]  # 30mm spacing along Y
    boss_r = 3.0
    hole_r = 1.5

    def top_z_at_xy(s, x, y, z_lo, z_hi):
        # Intersect a vertical line with the solid; use the highest z of intersection.
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
            # normals mostly horizontal => vertical faces
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
    # Classification uses edge adjacency:
    #   outer = edges whose BOTH adjacent faces are on the external envelope
    #   inner = remaining sharp-ish edges (still excluding bottom-plane edges)
    # -----------------------------
    def collect_edge_points_by_inner_outer(s, bottom_z, tol_env=1e-3):
        try:
            from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
            from OCP.TopExp import TopExp_Explorer, TopExp
            from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape
            from OCP.TopoDS import TopoDS
        except Exception as e:
            print(f"[DBG] WARN: OCP edge adjacency unavailable; will fall back to bbox-only classification. Error: {e}")
            return None, None

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

        gbb = s.BoundingBox()
        xmin, xmax = gbb.xmin, gbb.xmax
        ymin, ymax = gbb.ymin, gbb.ymax
        zmin, zmax = gbb.zmin, gbb.zmax

        def face_is_exterior(face_obj):
            bb = cq.Shape.cast(face_obj).BoundingBox()
            # Touching any global bbox boundary implies "external envelope".
            return (
                abs(bb.xmin - xmin) < tol_env or abs(bb.xmax - xmax) < tol_env or
                abs(bb.ymin - ymin) < tol_env or abs(bb.ymax - ymax) < tol_env or
                abs(bb.zmax - zmax) < tol_env or abs(bb.zmin - zmin) < tol_env
            )

        # Map edges -> adjacent faces
        amap = TopTools_IndexedDataMapOfShapeListOfShape()
        if hasattr(TopExp, "MapShapesAndAncestors_s"):
            TopExp.MapShapesAndAncestors_s(s.wrapped, TopAbs_EDGE, TopAbs_FACE, amap)
        else:
            # older bindings
            TopExp.MapShapesAndAncestors(s.wrapped, TopAbs_EDGE, TopAbs_FACE, amap)

        # Precompute exterior flags for faces (by HashCode)
        face_ext = {}
        fexp = TopExp_Explorer(s.wrapped, TopAbs_FACE)
        while fexp.More():
            fw = as_face(fexp.Current())
            try:
                h = fw.HashCode(2147483647)
                face_ext[h] = face_is_exterior(fw)
            except Exception:
                pass
            fexp.Next()

        outer_pts = []
        inner_pts = []

        eexp = TopExp_Explorer(s.wrapped, TopAbs_EDGE)
        total = two_face = skipped_bottom = classified = 0

        while eexp.More():
            total += 1
            ew = as_edge(eexp.Current())
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
            f1 = as_face(faces_list.First())
            f2 = as_face(faces_list.Last())

            try:
                h1 = f1.HashCode(2147483647)
                h2 = f2.HashCode(2147483647)
                ext1 = face_ext.get(h1, False)
                ext2 = face_ext.get(h2, False)
            except Exception:
                ext1 = ext2 = False

            # Edge representative point
            try:
                mp = cq.Shape.cast(ew).Center()
            except Exception:
                try:
                    mp = cq.Shape.cast(ew).BoundingBox().center
                except Exception:
                    eexp.Next()
                    continue

            classified += 1
            if ext1 and ext2:
                outer_pts.append((mp.x, mp.y, mp.z))
            else:
                inner_pts.append((mp.x, mp.y, mp.z))

            eexp.Next()

        print(f"[DBG] Edge classification: total={total} two_face={two_face} skipped_bottom={skipped_bottom} classified={classified} outer={len(outer_pts)} inner={len(inner_pts)}")
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

    def fillet_by_points_sequential(s, pts, radius, label, pick_tol=6.0, max_ops=10000):
        done = fail = skipped = 0
        bottom_z_local = s.BoundingBox().zmin
        for (x, y, z) in pts[:max_ops]:
            try:
                sel = cqs.NearestToPointSelector((x, y, z))
                e = cq.Workplane(obj=s).edges(sel).val()

                # ensure we don't fillet bottom-plane edges
                if is_edge_on_bottom(e, bottom_z_local, tol=1e-3):
                    skipped += 1
                    continue

                # midpoint proximity sanity
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

    outer_pts, inner_pts = collect_edge_points_by_inner_outer(solid, bb.zmin, tol_env=1e-3)

    # Fallback if OCP adjacency isn't available: bbox-only heuristic
    if outer_pts is None:
        gbb = solid.BoundingBox()
        xmax = max(abs(gbb.xmin), abs(gbb.xmax))
        ymax = max(abs(gbb.ymin), abs(gbb.ymax))
        zmax = gbb.zmax
        outer_pts = []
        inner_pts = []
        for e in solid.Edges():
            if is_edge_on_bottom(e, gbb.zmin, tol=1e-3):
                continue
            mp = e.Center()
            is_outer = (abs(mp.x) > 0.97 * xmax) or (abs(mp.y) > 0.97 * ymax) or (mp.z > zmax - 0.5)
            (outer_pts if is_outer else inner_pts).append((mp.x, mp.y, mp.z))
        print(f"[DBG] Fallback bbox-classification: outer={len(outer_pts)} inner={len(inner_pts)}")

    outer_pts = dedup_xyz(outer_pts, nd=2)
    inner_pts = dedup_xyz(inner_pts, nd=2)

    # Sort to increase robustness: do higher edges first
    outer_pts = sorted(outer_pts, key=lambda p: (-p[2], -abs(p[0]) - abs(p[1])))
    inner_pts = sorted(inner_pts, key=lambda p: (-p[2], abs(p[0]) + abs(p[1])))

    print(f"[DBG] Fillet target counts (dedup, excl bottom): outer={len(outer_pts)} inner={len(inner_pts)}")

    # 4) Outer fillets R=3mm
    solid = fillet_by_points_sequential(solid, outer_pts, 3.0, "outer R3", pick_tol=8.0)

    # 3) Inner fillets R=1mm
    solid = fillet_by_points_sequential(solid, inner_pts, 1.0, "inner R1", pick_tol=6.0)

    try:
        solid = cq.Workplane(obj=solid).combineSolids().val()
    except Exception:
        pass

    bb_end = solid.BoundingBox()
    print(f"[DBG] End bbox: x=({bb_end.xmin:.3f},{bb_end.xmax:.3f}) y=({bb_end.ymin:.3f},{bb_end.ymax:.3f}) z=({bb_end.zmin:.3f},{bb_end.zmax:.3f})")

    return cq.Workplane(obj=solid)
