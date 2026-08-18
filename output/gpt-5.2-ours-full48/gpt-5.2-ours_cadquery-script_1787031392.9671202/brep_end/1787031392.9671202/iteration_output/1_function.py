def my_cad_function(args):
    import cadquery as cq
    import os, math

    input_file = os.path.expanduser(args.get("input_file", ""))
    if not input_file or not os.path.exists(input_file):
        print(f"ERROR: input_file not found: {input_file}")
        return None

    # --- Load STEP ---
    try:
        wp_import = cq.importers.importStep(input_file)
    except Exception as e:
        print(f"ERROR importing STEP: {e}")
        return None

    shape = wp_import.val() if hasattr(wp_import, "val") else wp_import
    print(f"Loaded shape. Valid={shape.isValid()}")

    bbox = shape.BoundingBox()
    print(
        "Global BBox: "
        f"xmin={bbox.xmin:.3f} xmax={bbox.xmax:.3f} "
        f"ymin={bbox.ymin:.3f} ymax={bbox.ymax:.3f} "
        f"zmin={bbox.zmin:.3f} zmax={bbox.zmax:.3f}"
    )

    # --- Helpers ---
    def _is_planar(face):
        try:
            return face.geomType() == "PLANE"
        except Exception:
            return False

    def _area(face):
        try:
            return face.Area()
        except Exception:
            return 0.0

    faces = list(shape.Faces())
    top_cands = []
    bot_cands = []

    for f in faces:
        if not _is_planar(f):
            continue
        try:
            n = f.normalAt().normalized()
        except Exception:
            continue

        if n.y > 0.95:
            bb = f.BoundingBox()
            top_cands.append((f, _area(f), f.Center().y, bb.ymin, bb.ymax))
        elif n.y < -0.95:
            bb = f.BoundingBox()
            bot_cands.append((f, _area(f), f.Center().y, bb.ymin, bb.ymax))

    top_cands.sort(key=lambda t: t[1], reverse=True)
    bot_cands.sort(key=lambda t: t[1], reverse=True)

    print("Top planar +Y candidates (top 8):")
    for i, t in enumerate(top_cands[:8]):
        print(f"  {i}: area={t[1]:.1f} centerY={t[2]:.3f} yRange=[{t[3]:.3f},{t[4]:.3f}]")

    print("Bottom planar -Y candidates (top 8):")
    for i, t in enumerate(bot_cands[:8]):
        print(f"  {i}: area={t[1]:.1f} centerY={t[2]:.3f} yRange=[{t[3]:.3f},{t[4]:.3f}]")

    if not top_cands or not bot_cands:
        print("ERROR: Could not find suitable top/bottom planar faces with normals ~±Y")
        return cq.Workplane(obj=shape)

    top_face = top_cands[0][0]
    bot_face = bot_cands[0][0]

    # --- Slot pattern parameters (safe/conservative defaults) ---
    slot_len = 30.0     # mm
    slot_w = 6.0        # mm
    cut_depth = 2.0     # mm (blind-ish effect; implemented via subtracting shallow extrusions)
    edge_margin = 18.0  # mm keep-away from perimeter
    pitch_x = 28.0      # mm
    pitch_z = 28.0      # mm
    keepout_r = 45.0    # mm radial keepout around face center (avoid central boss region)

    def _build_plane_on_face(face):
        c = face.Center()
        n = face.normalAt().normalized()
        xDir = cq.Vector(1, 0, 0)
        # If xDir nearly parallel to normal, switch
        if abs(n.dot(xDir)) > 0.98:
            xDir = cq.Vector(0, 0, 1)
        return cq.Plane(origin=c, xDir=xDir, normal=n)

    def _slot_centers(face, plane):
        c = face.Center()
        fbb = face.BoundingBox()

        x0, x1 = fbb.xmin + edge_margin, fbb.xmax - edge_margin
        z0, z1 = fbb.zmin + edge_margin, fbb.zmax - edge_margin

        if x1 <= x0 or z1 <= z0:
            return []

        pts_local = []
        x = x0
        while x <= x1 + 1e-6:
            z = z0
            while z <= z1 + 1e-6:
                # circular keepout in global XZ about face center
                if math.hypot(x - c.x, z - c.z) >= keepout_r:
                    v_global = cq.Vector(x, c.y, z)
                    v_loc = plane.toLocalCoords(v_global)
                    pts_local.append((v_loc.x, v_loc.y))
                z += pitch_z
            x += pitch_x

        return pts_local

    def _make_cutters_for_face(face, tag=""):
        plane = _build_plane_on_face(face)
        pts = _slot_centers(face, plane)
        print(f"Generated {len(pts)} slot centers for {tag} face at centerY={face.Center().y:.3f}")
        if not pts:
            return None

        # Build slot profiles and extrude them along plane normal.
        # Using subtractive solids avoids Workplane.cutBlind misuse and works with imported shapes.
        w = cq.Workplane(plane).pushPoints(pts)
        try:
            w = w.slot2D(slot_len, slot_w, angle=90)
        except TypeError:
            # older CQ signature
            w = w.slot2D(slot_len, slot_w)

        # Extrude opposite of outward normal by using negative depth.
        cutters = w.extrude(-cut_depth, combine=False)
        return cutters

    base = cq.Workplane(obj=shape)

    top_cutters = _make_cutters_for_face(top_face, tag="TOP")
    bot_cutters = _make_cutters_for_face(bot_face, tag="BOTTOM")

    if top_cutters is None and bot_cutters is None:
        print("WARNING: No cutters created (no slot points). Returning original shape.")
        return base

    # Perform cuts (boolean subtraction)
    try:
        if top_cutters is not None:
            base = base.cut(top_cutters)
        if bot_cutters is not None:
            base = base.cut(bot_cutters)
    except Exception as e:
        print(f"ERROR during boolean cut: {e}")
        # Return original if booleans fail on invalid geometry
        return cq.Workplane(obj=shape)

    print("Slot pattern cut applied on top and bottom (via subtractive extruded cutters).")
    return base
