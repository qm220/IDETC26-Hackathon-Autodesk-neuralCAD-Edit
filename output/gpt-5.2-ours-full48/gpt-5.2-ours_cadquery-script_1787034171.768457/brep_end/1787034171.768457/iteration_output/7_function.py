def my_cad_function(args):
    import cadquery as cq
    import cadquery.selectors as cqs
    import os, math

    if "input_file" not in args:
        raise ValueError("Missing args['input_file']")

    input_file = os.path.expanduser(args["input_file"])
    wp_in = cq.importers.importStep(input_file)
    solid = wp_in.val()

    # Try to ensure a single solid
    try:
        solid = cq.Workplane(obj=solid).combineSolids().val()
    except Exception:
        pass

    print(f"[DBG] Imported shape type: {type(solid)}")

    # -----------------------------
    # 1) Scale uniformly 10x about origin
    # -----------------------------
    if not hasattr(solid, "scale"):
        raise RuntimeError("Loaded shape does not support .scale()")
    solid = solid.scale(10.0)

    bb = solid.BoundingBox()
    print(f"[DBG] After scale bbox: x=({bb.xmin:.3f},{bb.xmax:.3f}) y=({bb.ymin:.3f},{bb.ymax:.3f}) z=({bb.zmin:.3f},{bb.zmax:.3f})")

    # -----------------------------
    # 5) Two cylindrical features (OD=6, ID=3), spaced 30mm along Y, centered
    # Start at bottom Z-level and go up to the top surface at that XY
    # -----------------------------
    bb = solid.BoundingBox()
    bottom_z = bb.zmin

    pts = [(0.0, 15.0), (0.0, -15.0)]  # 30mm center-to-center along Y
    boss_r = 3.0
    hole_r = 1.5

    def top_z_at_xy(s, x, y, z_lo, z_hi):
        """Intersect a vertical line with the solid; return max Z of intersection."""
        line = cq.Edge.makeLine(cq.Vector(x, y, z_lo), cq.Vector(x, y, z_hi))
        try:
            common = s.intersect(line)
            cbb = common.BoundingBox()
            # If intersection is empty/degenerate
            if (cbb.zmax - cbb.zmin) < 1e-7:
                return None
            return cbb.zmax
        except Exception:
            return None

    bb = solid.BoundingBox()
    z_lo = bb.zmin - 500.0
    z_hi = bb.zmax + 500.0
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

        # Faces with normals near-horizontal are vertical walls (including cylinders)
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
    # Robust, bbox-based outer/inner classification:
    #   outer edges = edges that touch global envelope (xmin/xmax/ymin/ymax/zmax)
    #   inner edges = remaining edges (pocket, holes, internal intersections)
    # -----------------------------

    def edge_on_bottom(edge, z0, tol=1e-3):
        ebb = edge.BoundingBox()
        return abs(ebb.zmin - z0) < tol and abs(ebb.zmax - z0) < tol

    def edge_hash(edge):
        try:
            return edge.wrapped.HashCode(2147483647)
        except Exception:
            return id(edge)

    def dedup_edges(edges):
        seen = set()
        out = []
        for e in edges:
            h = edge_hash(e)
            if h in seen:
                continue
            seen.add(h)
            out.append(e)
        return out

    def collect_outer_inner_edges(s):
        bb = s.BoundingBox()
        xmin, xmax = bb.xmin, bb.xmax
        ymin, ymax = bb.ymin, bb.ymax
        zmin, zmax = bb.zmin, bb.zmax
        diag = math.sqrt((xmax - xmin) ** 2 + (ymax - ymin) ** 2 + (zmax - zmin) ** 2)
        tol_env = max(0.2, 0.0025 * diag)

        outer = []
        inner = []
        skipped_bottom = 0

        for e in s.Edges():
            if edge_on_bottom(e, zmin, tol=1e-3):
                skipped_bottom += 1
                continue
            ebb = e.BoundingBox()
            touches_env = (
                abs(ebb.xmin - xmin) < tol_env or abs(ebb.xmax - xmax) < tol_env or
                abs(ebb.ymin - ymin) < tol_env or abs(ebb.ymax - ymax) < tol_env or
                abs(ebb.zmax - zmax) < tol_env
            )
            if touches_env:
                outer.append(e)
            else:
                inner.append(e)

        outer = dedup_edges(outer)
        inner = dedup_edges(inner)

        print(f"[DBG] Edge classify: tol_env={tol_env:.3f} skipped_bottom={skipped_bottom} outer={len(outer)} inner={len(inner)}")
        return outer, inner

    def fillet_edges_bulk_or_fallback(s, edges, radius, label):
        if not edges:
            print(f"[DBG] Fillet {label}: no edges")
            return s

        # Try bulk fillet first
        try:
            wp = cq.Workplane(obj=s).newObject(edges).fillet(radius)
            out = wp.val()
            print(f"[DBG] Fillet {label}: bulk success edges={len(edges)}")
            return out
        except Exception as e:
            print(f"[DBG] Fillet {label}: bulk failed ({e}); falling back to iterative")

        # Fallback: iterative by nearest-to-point using edge centers
        pts = []
        for ed in edges:
            try:
                c = ed.Center()
                pts.append((c.x, c.y, c.z))
            except Exception:
                continue

        # Sort to improve robustness (do higher edges first)
        pts.sort(key=lambda p: (-p[2], abs(p[0]) + abs(p[1])))

        success = fail = skip = 0
        for (x, y, z) in pts:
            try:
                sel = cqs.NearestToPointSelector((x, y, z))
                e1 = cq.Workplane(obj=s).edges(sel).val()
                # Still respect bottom exclusion
                if edge_on_bottom(e1, s.BoundingBox().zmin, tol=1e-3):
                    skip += 1
                    continue
                s = cq.Workplane(obj=s).edges(sel).fillet(radius).val()
                success += 1
            except Exception:
                fail += 1

        print(f"[DBG] Fillet {label}: iterative success={success} fail={fail} skip={skip} (pts={len(pts)})")
        return s

    bb_pre = solid.BoundingBox()
    print(f"[DBG] Pre-fillet bbox: x=({bb_pre.xmin:.3f},{bb_pre.xmax:.3f}) y=({bb_pre.ymin:.3f},{bb_pre.ymax:.3f}) z=({bb_pre.zmin:.3f},{bb_pre.zmax:.3f})")

    outer_edges, inner_edges = collect_outer_inner_edges(solid)

    # 4) Outer rounds R=3mm (excluding bottom edges)
    solid = fillet_edges_bulk_or_fallback(solid, outer_edges, 3.0, "outer R3")

    # Recompute edges after topology change
    outer_edges2, inner_edges2 = collect_outer_inner_edges(solid)

    # 3) Inner rounds R=1mm (excluding bottom edges)
    solid = fillet_edges_bulk_or_fallback(solid, inner_edges2, 1.0, "inner R1")

    try:
        solid = cq.Workplane(obj=solid).combineSolids().val()
    except Exception:
        pass

    bb_end = solid.BoundingBox()
    print(f"[DBG] End bbox: x=({bb_end.xmin:.3f},{bb_end.xmax:.3f}) y=({bb_end.ymin:.3f},{bb_end.ymax:.3f}) z=({bb_end.zmin:.3f},{bb_end.zmax:.3f})")

    return cq.Workplane(obj=solid)
