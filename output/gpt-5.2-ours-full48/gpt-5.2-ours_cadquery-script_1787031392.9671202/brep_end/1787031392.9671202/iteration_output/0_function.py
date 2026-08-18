def my_cad_function(args):
    import cadquery as cq
    import os, math

    input_file = os.path.expanduser(args.get("input_file", ""))
    if not input_file or not os.path.exists(input_file):
        print(f"ERROR: input_file not found: {input_file}")
        return None

    # --- Load STEP ---
    try:
        wp = cq.importers.importStep(input_file)
    except Exception as e:
        print(f"ERROR importing STEP: {e}")
        return None

    shape = wp.val() if hasattr(wp, "val") else wp
    print(f"Loaded shape. Valid={shape.isValid()}")

    bbox = shape.BoundingBox()
    print(
        "Global BBox: "
        f"xmin={bbox.xmin:.3f} xmax={bbox.xmax:.3f} "
        f"ymin={bbox.ymin:.3f} ymax={bbox.ymax:.3f} "
        f"zmin={bbox.zmin:.3f} zmax={bbox.zmax:.3f}"
    )

    # --- Helper: find big planar top/bottom faces (normal approx +/-Y), prefer large area ---
    def _is_planar(f):
        try:
            return f.geomType() == "PLANE"
        except Exception:
            # fallback: if geomType not available, just try normalAt
            try:
                _ = f.normalAt()
                return True
            except Exception:
                return False

    def _face_area(f):
        try:
            return f.Area()
        except Exception:
            return 0.0

    faces = list(shape.Faces())

    top_cands = []
    bot_cands = []
    for f in faces:
        if not _is_planar(f):
            continue
        try:
            n = f.normalAt()
        except Exception:
            continue
        # near +/-Y
        if n.y > 0.95:
            top_cands.append((f, _face_area(f), f.Center().y, f.BoundingBox().ymin, f.BoundingBox().ymax))
        elif n.y < -0.95:
            bot_cands.append((f, _face_area(f), f.Center().y, f.BoundingBox().ymin, f.BoundingBox().ymax))

    top_cands.sort(key=lambda t: t[1], reverse=True)
    bot_cands.sort(key=lambda t: t[1], reverse=True)

    print("Top planar +Y candidates (top 8):")
    for i, t in enumerate(top_cands[:8]):
        print(f"  {i}: area={t[1]:.1f} centerY={t[2]:.3f} yRange=[{t[3]:.3f},{t[4]:.3f}]")

    print("Bottom planar -Y candidates (top 8):")
    for i, t in enumerate(bot_cands[:8]):
        print(f"  {i}: area={t[1]:.1f} centerY={t[2]:.3f} yRange=[{t[3]:.3f},{t[4]:.3f}]")

    if not top_cands or not bot_cands:
        print("ERROR: Could not find suitable top/bottom planar faces.")
        return wp

    top_face = top_cands[0][0]
    bot_face = bot_cands[0][0]

    # --- Slot pattern parameters (conservative defaults; can be tuned after first render) ---
    slot_len = 30.0   # mm
    slot_w = 6.0      # mm
    cut_depth = 2.0   # mm (blind, shallow for safety)
    edge_margin = 18.0
    pitch_x = 28.0
    pitch_z = 28.0
    keepout_r = 45.0  # mm radial keepout around face center (avoid central boss/cap)

    def _make_slot_points_on_face(face, outward_normal_hint):
        # Build a plane on the face with xDir aligned to global +X
        # (yDir is derived; sign doesn't matter because we convert points via toLocalCoords)
        c = face.Center()
        try:
            n = face.normalAt()
        except Exception:
            n = outward_normal_hint

        # Guard against xDir parallel to normal
        xDir = cq.Vector(1, 0, 0)
        if abs(n.normalized().dot(xDir)) > 0.98:
            xDir = cq.Vector(0, 0, 1)

        pln = cq.Plane(origin=c, xDir=xDir, normal=n)

        fbb = face.BoundingBox()
        x0, x1 = fbb.xmin + edge_margin, fbb.xmax - edge_margin
        z0, z1 = fbb.zmin + edge_margin, fbb.zmax - edge_margin

        if x1 <= x0 or z1 <= z0:
            print("WARNING: face too small after margins; skipping")
            return pln, []

        # Generate grid in GLOBAL X-Z, then convert to plane-local (u,v)
        pts_local = []
        x = x0
        while x <= x1 + 1e-6:
            z = z0
            while z <= z1 + 1e-6:
                # keepout around center (global x,z distance)
                if ((x - c.x) ** 2 + (z - c.z) ** 2) ** 0.5 >= keepout_r:
                    v_global = cq.Vector(x, c.y, z)
                    v_loc = pln.toLocalCoords(v_global)
                    pts_local.append((v_loc.x, v_loc.y))
                z += pitch_z
            x += pitch_x

        print(f"Generated {len(pts_local)} slot centers for face at centerY={c.y:.3f}")
        return pln, pts_local

    # Build point sets
    top_plane, top_pts = _make_slot_points_on_face(top_face, cq.Vector(0, 1, 0))
    bot_plane, bot_pts = _make_slot_points_on_face(bot_face, cq.Vector(0, -1, 0))

    result = wp

    # --- Cut slots on top ---
    if top_pts:
        wpt = cq.Workplane(top_plane).pushPoints(top_pts)
        # slot orientation: along plane local Y (i.e., generally global Z direction) => angle=90
        try:
            wpt = wpt.slot2D(slot_len, slot_w, angle=90)
        except TypeError:
            # older CQ: slot2D may not have angle param; fall back to default orientation
            wpt = wpt.slot2D(slot_len, slot_w)
        try:
            result = result.cutBlind(wpt, -cut_depth)
        except Exception:
            # fallback: do the cut via workplane chaining
            result = result.newObject([result.val()]).add(wpt.val()) if hasattr(result, 'val') else result
            result = cq.Workplane(obj=result).cutBlind(-cut_depth)

    # --- Cut slots on bottom ---
    if bot_pts:
        wpb = cq.Workplane(bot_plane).pushPoints(bot_pts)
        try:
            wpb = wpb.slot2D(slot_len, slot_w, angle=90)
        except TypeError:
            wpb = wpb.slot2D(slot_len, slot_w)
        try:
            result = result.cutBlind(wpb, -cut_depth)
        except Exception:
            result = result.newObject([result.val()]).add(wpb.val()) if hasattr(result, 'val') else result
            result = cq.Workplane(obj=result).cutBlind(-cut_depth)

    print("Slot pattern operation attempted (top and bottom).")
    return result
