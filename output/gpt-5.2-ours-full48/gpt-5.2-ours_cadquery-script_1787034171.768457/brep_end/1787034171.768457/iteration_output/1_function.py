def my_cad_function(args):
    import cadquery as cq
    import os, math

    if "input_file" not in args:
        raise ValueError("Missing args['input_file']")

    input_file = os.path.expanduser(args["input_file"])
    wp_in = cq.importers.importStep(input_file)
    shp_in = wp_in.val()

    # Try to ensure we are working with a single solid when possible
    try:
        shp_in = cq.Workplane(obj=shp_in).combineSolids().val()
    except Exception:
        pass

    print(f"[DBG] Imported shape type: {type(shp_in)}")

    # --- 1) Scale entire part uniformly 10x about origin ---
    if hasattr(shp_in, "scale"):
        solid = shp_in.scale(10.0)
    else:
        # Fallback using Workplane/Assembly transform if Shape.scale is unavailable
        # (rare in CQ2, but keep a guard)
        tr = cq.Matrix(
            [[10.0, 0.0, 0.0, 0.0],
             [0.0, 10.0, 0.0, 0.0],
             [0.0, 0.0, 10.0, 0.0],
             [0.0, 0.0, 0.0, 1.0]]
        )
        solid = shp_in.transformGeometry(tr)

    bb = solid.BoundingBox()
    print(f"[DBG] After scale bbox: x=({bb.xmin:.3f},{bb.xmax:.3f}) y=({bb.ymin:.3f},{bb.ymax:.3f}) z=({bb.zmin:.3f},{bb.zmax:.3f})")

    bottom_z = bb.zmin
    top_z = bb.zmax

    # Helpers
    def _is_planar_face(f):
        try:
            return f.geomType() == "PLANE"
        except Exception:
            return False

    def _face_normal_at_center(f):
        c = f.Center()
        try:
            return f.normalAt(c)
        except Exception:
            return f.normalAt()

    def _find_bottom_hinge_face(s):
        zmin = s.BoundingBox().zmin
        cands = []
        for f in s.Faces():
            if not _is_planar_face(f):
                continue
            fbb = f.BoundingBox()
            if abs(fbb.zmin - zmin) < 1e-3 and abs(fbb.zmax - zmin) < 1e-3:
                n = _face_normal_at_center(f)
                if n.z < -0.9:
                    cands.append(f)
        if not cands:
            return None
        return max(cands, key=lambda ff: ff.Area())

    def _edge_on_bottom(e, zmin_ref, t=1e-3):
        ebb = e.BoundingBox()
        return abs(ebb.zmin - zmin_ref) < t and abs(ebb.zmax - zmin_ref) < t

    def _edge_mid(e):
        try:
            return e.Center()
        except Exception:
            ebb = e.BoundingBox()
            return cq.Vector((ebb.xmin + ebb.xmax) / 2.0, (ebb.ymin + ebb.ymax) / 2.0, (ebb.zmin + ebb.zmax) / 2.0)

    # --- 5) Add two cylinder features (OD=6, ID=3), spaced 30mm, centered ---
    # Interpreting spacing along Y (symmetric): (0, ±15)
    pts = [(0.0, 15.0), (0.0, -15.0)]
    boss_r = 3.0
    hole_r = 1.5

    # Determine boss height by intersecting a vertical line at each center with the (scaled) solid.
    # This yields the top surface z at that XY, so boss reaches the top wall without protruding.
    def _top_z_at_xy(s, x, y, z_lo, z_hi):
        line = cq.Edge.makeLine(cq.Vector(x, y, z_lo), cq.Vector(x, y, z_hi))
        try:
            common = s.intersect(line)
            # common is the portion of the line inside the solid; its zmax corresponds to exit at top.
            cbb = common.BoundingBox()
            if (cbb.zmax - cbb.zmin) < 1e-6 and abs(cbb.zmax) < 1e-9:
                # heuristic for empty-ish result
                return None
            return cbb.zmax
        except Exception:
            return None

    z_lo = bottom_z - 5.0
    z_hi = top_z + 5.0

    for (x, y) in pts:
        zt = _top_z_at_xy(solid, x, y, z_lo, z_hi)
        if zt is None:
            zt = top_z
            print(f"[DBG] WARN: Could not ray-intersect top at ({x},{y}); using top_z={top_z:.3f}")
        height = max(0.1, zt - bottom_z)

        base_plane = cq.Plane(origin=(0, 0, bottom_z), normal=(0, 0, 1), xDir=(1, 0, 0))

        boss = cq.Workplane(base_plane).center(x, y).circle(boss_r).extrude(height).val()
        solid = solid.fuse(boss)

        hole = cq.Workplane(base_plane).center(x, y).circle(hole_r).extrude(height).val()
        solid = solid.cut(hole)

        print(f"[DBG] Boss at ({x:.1f},{y:.1f}) height={height:.3f} (bottom_z={bottom_z:.3f} -> z_top={zt:.3f})")

    # --- 2) Apply 2° draft to all vertical surfaces, hinge = bottom face, pull +Z ---
    hinge_face = _find_bottom_hinge_face(solid)
    if hinge_face is None:
        print("[DBG] WARN: bottom hinge face not found; skipping draft")
    else:
        vertical_faces = []
        for f in solid.Faces():
            # Identify vertical-ish faces by normal at center (works for planar and cylindrical)
            try:
                n = _face_normal_at_center(f)
            except Exception:
                continue
            if abs(n.z) < 0.2:
                vertical_faces.append(f)

        print(f"[DBG] Vertical faces selected for draft: {len(vertical_faces)}")

        if vertical_faces:
            try:
                solid = (
                    cq.Workplane(obj=solid)
                    .newObject(vertical_faces)
                    .draft(2.0, hinge_face, cq.Vector(0, 0, 1))
                    .val()
                )
                print("[DBG] Draft applied")
            except Exception as e:
                print(f"[DBG] WARN: Draft failed; continuing without draft. Error: {e}")

    # --- 3 & 4) Fillets: inner R=1, outer R=3; exclude any edges on the flat bottom surface ---
    bb2 = solid.BoundingBox()
    xMax = max(abs(bb2.xmin), abs(bb2.xmax))
    yMax = max(abs(bb2.ymin), abs(bb2.ymax))
    zmin2 = bb2.zmin

    # Classify edges with simple geometric heuristics + boss perimeter detection
    all_edges = list(solid.Edges())
    non_bottom_edges = [e for e in all_edges if not _edge_on_bottom(e, zmin2, t=1e-3)]

    # Tolerances for classification
    shell_tol = 0.35  # mm
    boss_tol = 0.60

    outer_shell_edges = []
    outer_boss_edges = []
    inner_edges = []

    for e in non_bottom_edges:
        m = _edge_mid(e)
        # Outer shell proximity (by x/y extremes)
        near_shell = (abs(abs(m.x) - xMax) < shell_tol) or (abs(abs(m.y) - yMax) < shell_tol)

        # Boss outer perimeter proximity in XY
        near_boss_outer = False
        for (cx, cy) in pts:
            d = math.hypot(m.x - cx, m.y - cy)
            if abs(d - boss_r) < boss_tol:
                near_boss_outer = True
                break

        if near_shell:
            outer_shell_edges.append(e)
        elif near_boss_outer:
            outer_boss_edges.append(e)
        else:
            inner_edges.append(e)

    print(
        f"[DBG] Edge counts (excluding bottom edges): total={len(non_bottom_edges)} "
        f"outer_shell={len(outer_shell_edges)} outer_boss={len(outer_boss_edges)} inner={len(inner_edges)}"
    )

    # Apply outer fillets first (R=3)
    if outer_shell_edges:
        try:
            solid = cq.Workplane(obj=solid).newObject(outer_shell_edges).fillet(3.0).val()
            print("[DBG] Outer fillet R=3 applied (shell)")
        except Exception as e:
            print(f"[DBG] WARN: Outer shell fillet R=3 failed. Error: {e}")

    if outer_boss_edges:
        try:
            solid = cq.Workplane(obj=solid).newObject(outer_boss_edges).fillet(3.0).val()
            print("[DBG] Outer fillet R=3 applied (bosses)")
        except Exception as e:
            print(f"[DBG] WARN: Outer boss fillet R=3 failed. Error: {e}")

    # Recompute bottom z (fillet doesn't touch it, but keep consistent)
    zmin3 = solid.BoundingBox().zmin

    # Apply inner fillets (R=1), excluding bottom edges again
    inner_edges2 = [e for e in solid.Edges() if not _edge_on_bottom(e, zmin3, t=1e-3)]

    # Reduce the inner set: avoid re-fillet obvious outer boundaries (x/y extremes, bosses outer)
    filtered_inner = []
    bb3 = solid.BoundingBox()
    xMax3 = max(abs(bb3.xmin), abs(bb3.xmax))
    yMax3 = max(abs(bb3.ymin), abs(bb3.ymax))
    for e in inner_edges2:
        m = _edge_mid(e)
        near_shell = (abs(abs(m.x) - xMax3) < shell_tol) or (abs(abs(m.y) - yMax3) < shell_tol)
        near_boss_outer = False
        for (cx, cy) in pts:
            d = math.hypot(m.x - cx, m.y - cy)
            if abs(d - boss_r) < boss_tol:
                near_boss_outer = True
                break
        if not near_shell and not near_boss_outer:
            filtered_inner.append(e)

    print(f"[DBG] Inner-edge candidates for R=1 (excluding bottom & likely-outer): {len(filtered_inner)}")

    if filtered_inner:
        try:
            solid = cq.Workplane(obj=solid).newObject(filtered_inner).fillet(1.0).val()
            print("[DBG] Inner fillet R=1 applied")
        except Exception as e:
            print(f"[DBG] WARN: Inner fillet R=1 failed. Error: {e}")

    return cq.Workplane(obj=solid)
