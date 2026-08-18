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

    def _safe_normal(face):
        try:
            return face.normalAt().normalized()
        except Exception:
            return None

    def _build_plane_on_face(face):
        c = face.Center()
        n = _safe_normal(face)
        if n is None:
            n = cq.Vector(0, 1, 0)
        xDir = cq.Vector(1, 0, 0)
        if abs(n.dot(xDir)) > 0.98:
            xDir = cq.Vector(0, 0, 1)
        return cq.Plane(origin=c, xDir=xDir, normal=n)

    def _detect_central_circular_keepout(face, plane, prefer_center=True):
        """Try to find a circular edge on the planar face that likely corresponds to a boss/feature.
        Returns (cx, cz, keepout_r) in GLOBAL coords, or None.
        """
        fbb = face.BoundingBox()
        xSpan = fbb.xmax - fbb.xmin
        zSpan = fbb.zmax - fbb.zmin
        max_reasonable = 0.6 * min(xSpan, zSpan)
        min_reasonable = 8.0

        fc = face.Center()
        best = None
        best_score = -1e9

        for e in face.Edges():
            try:
                if e.geomType() != "CIRCLE":
                    continue
            except Exception:
                continue
            try:
                circ = e._geomAdaptor().Circle()
                r = float(circ.Radius())
                center = circ.Location()
                cx, cy, cz = float(center.X()), float(center.Y()), float(center.Z())
            except Exception:
                continue

            if r < min_reasonable or r > max_reasonable:
                continue

            # Prefer circles whose centers are near face center in XZ
            d = math.hypot(cx - fc.x, cz - fc.z)
            # Score: big radius is good, being near center is good
            score = (r * 10.0) - (d * (3.0 if prefer_center else 1.0))
            if score > best_score:
                best_score = score
                best = (cx, cz, r)

        if best is None:
            return None

        cx, cz, r = best
        keepout_r = r + 12.0  # padding
        print(f"Detected circular keepout: center=({cx:.3f},{cz:.3f}) r={r:.3f} -> keepout_r={keepout_r:.3f}")
        return (cx, cz, keepout_r)

    # --- Find TOP/BOTTOM faces (planar, normals ~ ±Y) ---
    faces = list(shape.Faces())
    top_cands = []
    bot_cands = []

    for f in faces:
        if not _is_planar(f):
            continue
        n = _safe_normal(f)
        if n is None:
            continue
        bb = f.BoundingBox()
        if n.y > 0.95:
            top_cands.append((f, _area(f), f.Center().y, bb.ymin, bb.ymax))
        elif n.y < -0.95:
            bot_cands.append((f, _area(f), f.Center().y, bb.ymin, bb.ymax))

    top_cands.sort(key=lambda t: t[1], reverse=True)
    bot_cands.sort(key=lambda t: t[1], reverse=True)

    print("Top planar +Y candidates (top 6):")
    for i, t in enumerate(top_cands[:6]):
        print(f"  {i}: area={t[1]:.1f} centerY={t[2]:.3f} yRange=[{t[3]:.3f},{t[4]:.3f}]")

    print("Bottom planar -Y candidates (top 6):")
    for i, t in enumerate(bot_cands[:6]):
        print(f"  {i}: area={t[1]:.1f} centerY={t[2]:.3f} yRange=[{t[3]:.3f},{t[4]:.3f}]")

    if not top_cands or not bot_cands:
        print("ERROR: Could not find suitable top/bottom planar faces with normals ~±Y")
        return cq.Workplane(obj=shape)

    top_face = top_cands[0][0]
    bot_face = bot_cands[0][0]

    # --- Slot pattern parameters (adjusted to avoid overlap/merging) ---
    slot_len = 22.0     # mm
    slot_w = 6.0        # mm
    cut_depth = 2.0     # mm (blind-ish)
    edge_margin = 16.0  # mm
    gap_z = 14.0        # mm gap between slots along Z
    pitch_z = slot_len + gap_z
    pitch_x = 18.0      # mm (only used if face is wide enough)

    def _slot_centers(face):
        plane = _build_plane_on_face(face)
        fbb = face.BoundingBox()
        fc = face.Center()

        xSpan = fbb.xmax - fbb.xmin
        zSpan = fbb.zmax - fbb.zmin
        print(f"Face @Y={fc.y:.3f}: xSpan={xSpan:.3f} zSpan={zSpan:.3f} area={_area(face):.1f}")

        # Detect a likely circular boss/feature keepout on this face (if present)
        keepout = _detect_central_circular_keepout(face, plane)
        if keepout is None:
            # modest default keepout only if face appears to have a central boss-like region (heuristic)
            keepout_cx, keepout_cz, keepout_r = (fc.x, fc.z, 0.0)
        else:
            keepout_cx, keepout_cz, keepout_r = keepout

        x0, x1 = fbb.xmin + edge_margin, fbb.xmax - edge_margin
        z0, z1 = fbb.zmin + edge_margin, fbb.zmax - edge_margin
        if x1 <= x0 or z1 <= z0:
            return plane, []

        # If face is narrow in X, use a single centered column to truly be "across" the surface width.
        narrow_x_thresh = slot_w + 2.0 * edge_margin + 2.0
        if xSpan < narrow_x_thresh:
            xs = [0.5 * (fbb.xmin + fbb.xmax)]
        else:
            # multiple columns
            xs = []
            x = x0
            while x <= x1 + 1e-6:
                xs.append(x)
                x += pitch_x

        # Rows along Z
        zs = []
        z = z0
        while z <= z1 + 1e-6:
            zs.append(z)
            z += pitch_z

        pts_local = []
        for x in xs:
            for z in zs:
                if keepout_r > 1e-6 and math.hypot(x - keepout_cx, z - keepout_cz) < keepout_r:
                    continue
                v_global = cq.Vector(x, fc.y, z)
                v_loc = plane.toLocalCoords(v_global)
                pts_local.append((v_loc.x, v_loc.y))

        return plane, pts_local

    def _make_cutters_for_face(face, tag=""):
        plane, pts = _slot_centers(face)
        print(f"Generated {len(pts)} slot centers for {tag}")
        if not pts:
            return None

        w = cq.Workplane(plane).pushPoints(pts)
        # Slot along global Z (local Y) by using angle=90
        try:
            w = w.slot2D(slot_len, slot_w, angle=90)
        except TypeError:
            w = w.slot2D(slot_len, slot_w)

        cutters = w.extrude(-cut_depth, combine=False)
        return cutters

    base = cq.Workplane(obj=shape)

    top_cutters = _make_cutters_for_face(top_face, tag="TOP")
    bot_cutters = _make_cutters_for_face(bot_face, tag="BOTTOM")

    if top_cutters is None and bot_cutters is None:
        print("WARNING: No cutters created (no slot points). Returning original shape.")
        return base

    try:
        if top_cutters is not None:
            base = base.cut(top_cutters)
        if bot_cutters is not None:
            base = base.cut(bot_cutters)
    except Exception as e:
        print(f"ERROR during boolean cut: {e}")
        return cq.Workplane(obj=shape)

    print("Slot pattern cut applied on top and bottom (non-overlapping pitch).")
    return base
