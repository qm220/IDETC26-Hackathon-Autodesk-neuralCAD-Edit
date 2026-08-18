def my_cad_function(args):
    import cadquery as cq
    import os, math

    if "input_file" not in args:
        raise ValueError("Missing args['input_file']")

    input_file = os.path.expanduser(args["input_file"])
    wp_in = cq.importers.importStep(input_file)
    solid = wp_in.val()

    # Ensure single solid if possible
    try:
        solid = cq.Workplane(obj=solid).combineSolids().val()
    except Exception:
        pass

    print(f"[DBG] Imported: {type(solid)}")

    # -----------------------------
    # 1) Uniform scale 10x about origin
    # -----------------------------
    solid = solid.scale(10.0)
    bb = solid.BoundingBox()
    print(f"[DBG] After scale bbox: x=({bb.xmin:.3f},{bb.xmax:.3f}) y=({bb.ymin:.3f},{bb.ymax:.3f}) z=({bb.zmin:.3f},{bb.zmax:.3f})")

    # -----------------------------
    # Helpers: point-in-solid classifier (for edge convex/concave + top sampling)
    # -----------------------------
    try:
        from OCP.BRepClass3d import BRepClass3d_SolidClassifier
        from OCP.gp import gp_Pnt
        from OCP.TopAbs import TopAbs_IN, TopAbs_ON
        _have_classifier = True
    except Exception as e:
        print(f"[DBG] WARN: Solid classifier unavailable: {e}")
        _have_classifier = False

    def is_inside(shape, v, tol=1e-7):
        if not _have_classifier:
            return False
        c = BRepClass3d_SolidClassifier(shape.wrapped)
        c.Perform(gp_Pnt(v.x, v.y, v.z), tol)
        st = c.State()
        return (st == TopAbs_IN) or (st == TopAbs_ON)

    # -----------------------------
    # 5) Add two tube features (OD=6, ID=3), spaced 30mm along Y, centered
    # Start at bottom Z-level and extend upward (conservatively) up to the top wall
    # We compute a safe height from the minimum top-surface Z within the boss footprint
    # so bosses do NOT protrude above the top curved surface.
    # -----------------------------
    bb = solid.BoundingBox()
    bottom_z = bb.zmin
    base_plane = cq.Plane(origin=(0, 0, bottom_z), normal=(0, 0, 1), xDir=(1, 0, 0))

    pts = [(0.0, 15.0), (0.0, -15.0)]  # 30mm center-to-center along Y
    boss_r = 3.0
    hole_r = 1.5

    def top_z_at_xy_outer(shape, x, y, z_hi, z_lo, step=0.5):
        """Find top boundary Z along a vertical line at (x,y) by scanning down from above.
        Returns boundary Z (approx)."""
        if not _have_classifier:
            return shape.BoundingBox().zmax

        # scan down to find first inside
        z = z_hi
        found_in = None
        while z >= z_lo:
            if is_inside(shape, cq.Vector(x, y, z)):
                found_in = z
                break
            z -= step
        if found_in is None:
            return None

        z_in = found_in
        z_out = found_in + step

        # binary search boundary between OUT (above) and IN (below)
        for _ in range(35):
            zm = 0.5 * (z_in + z_out)
            if is_inside(shape, cq.Vector(x, y, zm)):
                z_in = zm
            else:
                z_out = zm
        return z_in

    bb = solid.BoundingBox()
    z_hi = bb.zmax + 50.0
    z_lo = bb.zmin - 50.0

    # Sample points on boss footprint to avoid top protrusion on curved saddle
    angs = [i * math.pi / 4 for i in range(8)]
    samples_unit = [(0.0, 0.0)] + [(math.cos(a), math.sin(a)) for a in angs]

    for (cx, cy) in pts:
        ztops = []
        for (ux, uy) in samples_unit:
            sx = cx + boss_r * ux
            sy = cy + boss_r * uy
            zt = top_z_at_xy_outer(solid, sx, sy, z_hi, z_lo, step=0.5)
            if zt is not None:
                ztops.append(zt)

        if not ztops:
            # fallback to bbox top
            z_top = solid.BoundingBox().zmax
            print(f"[DBG] WARN: could not sample top surface near ({cx},{cy}); using z_top={z_top:.3f}")
        else:
            # conservative height to keep boss entirely under the top surface
            z_top = min(ztops)

        height = max(0.2, z_top - bottom_z)

        boss = cq.Workplane(base_plane).center(cx, cy).circle(boss_r).extrude(height).val()
        solid = solid.fuse(boss)

        hole = cq.Workplane(base_plane).center(cx, cy).circle(hole_r).extrude(height).val()
        solid = solid.cut(hole)

        print(f"[DBG] Tube at ({cx:.1f},{cy:.1f}) height={height:.3f} (bottom_z={bottom_z:.3f} -> z_top(min-footprint)={z_top:.3f})")

    try:
        solid = cq.Workplane(obj=solid).combineSolids().val()
    except Exception:
        pass

    # -----------------------------
    # 2) Draft: 2 degrees on vertical planar and vertical cylindrical faces
    # Neutral/hinge plane: bottom plane z = zmin, pull dir +Z
    # -----------------------------
    def apply_draft(shape, angle_deg=2.0):
        try:
            from OCP.BRepOffsetAPI import BRepOffsetAPI_DraftAngle
            from OCP.BRepAdaptor import BRepAdaptor_Surface
            from OCP.GeomAbs import GeomAbs_Plane, GeomAbs_Cylinder
            from OCP.gp import gp_Dir, gp_Pln, gp_Pnt
        except Exception as e:
            print(f"[DBG] WARN: Draft unavailable, skipping. {e}")
            return shape

        bb2 = shape.BoundingBox()
        zmin = bb2.zmin
        neutral = gp_Pln(gp_Pnt(0, 0, zmin), gp_Dir(0, 0, 1))
        pull_dir = gp_Dir(0, 0, 1)

        vert_faces = []
        for f in shape.Faces():
            try:
                ad = BRepAdaptor_Surface(f.wrapped, True)
                st = ad.GetType()
                if st == GeomAbs_Plane:
                    # vertical plane: normal ~ horizontal
                    n = f.normalAt(f.Center())
                    if abs(n.z) < 0.05:
                        vert_faces.append(f)
                elif st == GeomAbs_Cylinder:
                    # vertical cylinder: axis ~ Z
                    ax = ad.Cylinder().Axis().Direction()
                    if abs(ax.Z()) > 0.95:
                        vert_faces.append(f)
            except Exception:
                continue

        print(f"[DBG] Draft vertical faces selected: {len(vert_faces)}")
        if not vert_faces:
            return shape

        ang = math.radians(angle_deg)

        def _try(angle_rad):
            da = BRepOffsetAPI_DraftAngle(shape.wrapped)
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

        out = _try(ang)
        if out is None:
            print("[DBG] WARN: Draft (+) failed; trying negative")
            out = _try(-ang)
        if out is None:
            print("[DBG] WARN: Draft failed; continuing without draft")
            return shape

        print("[DBG] Draft applied")
        return out

    solid = apply_draft(solid, 2.0)

    # -----------------------------
    # 3 & 4) Fillets:
    # Inner edges (concave) R=1mm, Outer edges (convex) R=3mm
    # Exclude edges lying on the flat bottom surface (z=zmin)
    # Concave/convex classification by probing along (n1+n2) bisector and testing inside.
    # -----------------------------
    def edge_on_bottom(edge, z0, tol=1e-3):
        eb = edge.BoundingBox()
        return abs(eb.zmin - z0) < tol and abs(eb.zmax - z0) < tol

    def edge_len(e):
        try:
            return float(e.Length())
        except Exception:
            return 0.0

    def classify_edges_concave_convex(shape, eps=0.2):
        if not _have_classifier:
            # Fallback: treat all non-bottom edges as outer to at least apply R3
            zmin = shape.BoundingBox().zmin
            all_edges = [e for e in shape.Edges() if not edge_on_bottom(e, zmin, 1e-3)]
            return [], all_edges

        # Map edges->adjacent faces
        try:
            from OCP.TopExp import TopExp
            from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape
            from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
        except Exception as e:
            print(f"[DBG] WARN: Topology mapping unavailable: {e}")
            zmin = shape.BoundingBox().zmin
            all_edges = [e for e in shape.Edges() if not edge_on_bottom(e, zmin, 1e-3)]
            return [], all_edges

        m = TopTools_IndexedDataMapOfShapeListOfShape()
        TopExp.MapShapesAndAncestors(shape.wrapped, TopAbs_EDGE, TopAbs_FACE, m)

        zmin = shape.BoundingBox().zmin
        concave = []
        convex = []
        skipped = 0
        for e in shape.Edges():
            if edge_on_bottom(e, zmin, 1e-3):
                skipped += 1
                continue
            try:
                lst = m.FindFromKey(e.wrapped)
            except Exception:
                continue
            # Need two adjacent faces to decide
            try:
                nfaces = lst.Size()
            except Exception:
                nfaces = 0
            if nfaces < 2:
                continue

            # Take first two faces
            try:
                f1 = cq.Face.cast(lst.First())
                f2 = cq.Face.cast(lst.Last())
            except Exception:
                continue

            try:
                p = e.Center()
                n1 = f1.normalAt(p)
                n2 = f2.normalAt(p)
                b = cq.Vector(n1.x + n2.x, n1.y + n2.y, n1.z + n2.z)
                bl = math.sqrt(b.x * b.x + b.y * b.y + b.z * b.z)
                if bl < 1e-9:
                    continue
                b = cq.Vector(b.x / bl, b.y / bl, b.z / bl)
                probe = cq.Vector(p.x + eps * b.x, p.y + eps * b.y, p.z + eps * b.z)
                inside = is_inside(shape, probe)
                if inside:
                    concave.append(e)
                else:
                    convex.append(e)
            except Exception:
                continue

        # Dedup by hash
        def _ehash(ed):
            try:
                return ed.wrapped.HashCode(2147483647)
            except Exception:
                return id(ed)

        def _dedup(lst):
            seen = set()
            out = []
            for ed in lst:
                h = _ehash(ed)
                if h in seen:
                    continue
                seen.add(h)
                out.append(ed)
            return out

        concave = _dedup(concave)
        convex = _dedup(convex)
        print(f"[DBG] Edge classify (concave/convex): skipped_bottom={skipped} concave={len(concave)} convex={len(convex)}")
        return concave, convex

    def fillet_edges(shape, edges, radius, label):
        if not edges:
            print(f"[DBG] Fillet {label}: no edges")
            return shape

        # Try bulk first
        try:
            out = cq.Workplane(obj=shape).newObject(edges).fillet(radius).val()
            print(f"[DBG] Fillet {label}: bulk success edges={len(edges)}")
            return out
        except Exception as e:
            print(f"[DBG] Fillet {label}: bulk failed ({e}); trying iterative")

        # Iterative: longest edges first
        edges_sorted = sorted(edges, key=edge_len, reverse=True)
        ok = fail = 0
        for ed in edges_sorted:
            try:
                shape = cq.Workplane(obj=shape).newObject([ed]).fillet(radius).val()
                ok += 1
            except Exception:
                fail += 1
        print(f"[DBG] Fillet {label}: iterative ok={ok} fail={fail} (target={len(edges_sorted)})")
        return shape

    bb_pre = solid.BoundingBox()
    print(f"[DBG] Pre-fillet bbox: x=({bb_pre.xmin:.3f},{bb_pre.xmax:.3f}) y=({bb_pre.ymin:.3f},{bb_pre.ymax:.3f}) z=({bb_pre.zmin:.3f},{bb_pre.zmax:.3f})")

    # Inner (concave) first, then outer (convex)
    concave_edges, convex_edges = classify_edges_concave_convex(solid, eps=0.2)
    solid = fillet_edges(solid, concave_edges, 1.0, "inner/concave R1")

    # Reclassify after topology change
    concave_edges2, convex_edges2 = classify_edges_concave_convex(solid, eps=0.2)
    solid = fillet_edges(solid, convex_edges2, 3.0, "outer/convex R3")

    try:
        solid = cq.Workplane(obj=solid).combineSolids().val()
    except Exception:
        pass

    bb_end = solid.BoundingBox()
    print(f"[DBG] End bbox: x=({bb_end.xmin:.3f},{bb_end.xmax:.3f}) y=({bb_end.ymin:.3f},{bb_end.ymax:.3f}) z=({bb_end.zmin:.3f},{bb_end.zmax:.3f})")

    return cq.Workplane(obj=solid)
