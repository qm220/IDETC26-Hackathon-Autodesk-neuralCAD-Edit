def my_cad_function(args):
    import cadquery as cq
    import os
    import math

    if "input_file" not in args:
        raise ValueError("Missing args['input_file'] for edit operation")

    input_file = os.path.expanduser(args["input_file"])
    wp = cq.importers.importStep(input_file)

    # ---- Scale 10x about origin ----
    wp = wp.scale(10.0)
    solid = wp.val()
    bb = solid.BoundingBox()
    print(f"[DBG] After scale: bbox x=({bb.xmin:.3f},{bb.xmax:.3f}) y=({bb.ymin:.3f},{bb.ymax:.3f}) z=({bb.zmin:.3f},{bb.zmax:.3f})")

    bottom_z = bb.zmin
    top_z = bb.zmax
    height = top_z - bottom_z

    # ---- Find bottom planar face to use as hinge/neutral face for draft ----
    def _is_planar_face(f):
        try:
            return f.geomType() == "PLANE"
        except Exception:
            return False

    def _face_normal(f):
        # normalAt() with no args returns normal near center in CQ
        try:
            return f.normalAt()
        except Exception:
            # fallback: use center point normal
            c = f.Center()
            return f.normalAt(c)

    tol = 1e-3
    bottom_candidates = []
    for f in solid.Faces():
        if not _is_planar_face(f):
            continue
        n = _face_normal(f)
        fbb = f.BoundingBox()
        # planar face at global minimum Z
        if abs(fbb.zmin - bottom_z) < 1e-2 and abs(fbb.zmax - bottom_z) < 1e-2 and n.z < -0.9:
            bottom_candidates.append(f)

    bottom_face = None
    if bottom_candidates:
        # choose the largest-area candidate
        bottom_face = max(bottom_candidates, key=lambda ff: ff.Area())
        print(f"[DBG] Bottom hinge face found. Area={bottom_face.Area():.3f}")
    else:
        print("[DBG] WARNING: bottom hinge face not found via heuristic; draft may fail")

    # ---- Add two tubular cylinders (OD=6, ID=3) spaced 30mm apart, centered ----
    # Interpreted as along Y axis: (0, ±15)
    base_plane = cq.Plane(origin=(0, 0, bottom_z), normal=(0, 0, 1), xDir=(1, 0, 0))
    pts = [(0, 15.0), (0, -15.0)]

    bosses = (
        cq.Workplane(base_plane)
        .pushPoints(pts)
        .circle(6.0 / 2.0)
        .extrude(height)
    )
    solid2 = solid.union(bosses)

    holes = (
        cq.Workplane(base_plane)
        .pushPoints(pts)
        .circle(3.0 / 2.0)
        .extrude(height)
    )
    solid2 = solid2.cut(holes)

    print(f"[DBG] Added 2 tube bosses (OD6/ID3) with height {height:.3f} from z={bottom_z:.3f} to z={top_z:.3f}")

    # ---- Draft 2 degrees on vertical planar faces (hinge = bottom face, pull +Z) ----
    # Note: Drafting cylindrical faces can be fragile; we draft only planar vertical faces.
    vertical_planar_faces = []
    for f in solid2.Faces():
        if not _is_planar_face(f):
            continue
        n = _face_normal(f)
        if abs(n.z) < 0.1:  # vertical-ish
            vertical_planar_faces.append(f)

    print(f"[DBG] Vertical planar faces selected for draft: {len(vertical_planar_faces)}")

    drafted = solid2
    if bottom_face is not None and vertical_planar_faces:
        try:
            drafted = (
                cq.Workplane(obj=solid2)
                .newObject(vertical_planar_faces)
                .draft(2.0, bottom_face, cq.Vector(0, 0, 1))
                .val()
            )
            print("[DBG] Draft applied successfully")
        except Exception as e:
            print(f"[DBG] Draft FAILED, continuing without draft. Error: {e}")
            drafted = solid2

    # ---- Fillets: outer R=3, inner R=1; exclude edges on bottom plane ----
    bb2 = drafted.BoundingBox()
    xMax = max(abs(bb2.xmin), abs(bb2.xmax))
    yMax = max(abs(bb2.ymin), abs(bb2.ymax))
    z0 = bb2.zmin

    def _edge_on_bottom(e, zmin_ref, t=1e-2):
        ebb = e.BoundingBox()
        return abs(ebb.zmin - zmin_ref) < t and abs(ebb.zmax - zmin_ref) < t

    def _edge_mid(e):
        try:
            return e.Center()
        except Exception:
            # fallback: midpoint of bounding box
            ebb = e.BoundingBox()
            return cq.Vector((ebb.xmin + ebb.xmax) / 2.0, (ebb.ymin + ebb.ymax) / 2.0, (ebb.zmin + ebb.zmax) / 2.0)

    all_edges = list(drafted.Edges())
    non_bottom_edges = [e for e in all_edges if not _edge_on_bottom(e, z0)]

    outer_edges = []
    inner_edges = []
    for e in non_bottom_edges:
        m = _edge_mid(e)
        rx = abs(m.x) / (xMax if xMax > 1e-9 else 1.0)
        ry = abs(m.y) / (yMax if yMax > 1e-9 else 1.0)
        r = max(rx, ry)
        # heuristic separation: near outer boundary => outer, otherwise inner
        if r >= 0.975:
            outer_edges.append(e)
        else:
            inner_edges.append(e)

    print(f"[DBG] Non-bottom edges: {len(non_bottom_edges)}; outer_edges={len(outer_edges)}; inner_edges={len(inner_edges)}")

    result = drafted

    # Outer fillet R=3
    if outer_edges:
        try:
            result = cq.Workplane(obj=result).newObject(outer_edges).fillet(3.0).val()
            print("[DBG] Outer fillet R=3 applied")
        except Exception as e:
            print(f"[DBG] Outer fillet FAILED (R=3). Error: {e}")

    # Inner fillet R=1
    if inner_edges:
        try:
            result = cq.Workplane(obj=result).newObject(inner_edges).fillet(1.0).val()
            print("[DBG] Inner fillet R=1 applied")
        except Exception as e:
            print(f"[DBG] Inner fillet FAILED (R=1). Error: {e}")

    return cq.Workplane(obj=result)
