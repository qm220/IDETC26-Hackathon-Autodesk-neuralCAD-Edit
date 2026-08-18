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

    # ---------------- Helpers ----------------
    def _is_planar(face):
        try:
            return face.geomType() == "PLANE"
        except Exception:
            return False

    def _area(face):
        try:
            return float(face.Area())
        except Exception:
            return 0.0

    def _safe_normal(face):
        try:
            return face.normalAt().normalized()
        except Exception:
            return None

    def _build_plane_on_face(face):
        c = face.Center()
        n = _safe_normal(face) or cq.Vector(0, 1, 0)
        # choose stable xDir not parallel to normal
        xDir = cq.Vector(1, 0, 0)
        if abs(n.dot(xDir)) > 0.98:
            xDir = cq.Vector(0, 0, 1)
        return cq.Plane(origin=c, xDir=xDir, normal=n)

    def _centered_coords(v0, v1, pitch, force_min_count=1):
        """Return centered coordinate list in [v0,v1] using ~pitch spacing."""
        if v1 <= v0:
            return [0.5 * (v0 + v1)]
        span = v1 - v0
        if pitch <= 1e-6:
            return [0.5 * (v0 + v1)]
        n = int(math.floor(span / pitch)) + 1
        n = max(force_min_count, n)
        if n == 1:
            return [0.5 * (v0 + v1)]
        mid = 0.5 * (v0 + v1)
        start = mid - 0.5 * (n - 1) * pitch
        coords = [start + i * pitch for i in range(n)]
        coords = [c for c in coords if (v0 - 1e-6) <= c <= (v1 + 1e-6)]
        return coords if coords else [mid]

    def _wire_keepouts_on_face(face, pad):
        """Build keepout circles around any inner wires on the selected planar face.
        This is more robust than scanning global edges for CIRCLE, because STEP may
        encode hole/boss boundaries as non-circle curves."""
        keepouts = []
        try:
            inner_wires = list(face.innerWires())
        except Exception:
            inner_wires = []

        for w in inner_wires:
            try:
                bb = w.BoundingBox()
                cx = 0.5 * (bb.xmin + bb.xmax)
                cz = 0.5 * (bb.zmin + bb.zmax)
                dx = (bb.xmax - bb.xmin)
                dz = (bb.zmax - bb.zmin)
                # radius that fully covers the wire's bbox, plus padding
                r = 0.5 * max(dx, dz) + pad
                if r > 1.0:
                    keepouts.append((cx, cz, r))
            except Exception:
                continue

        # de-dupe similar keepouts
        merged = []
        for (cx, cz, r) in keepouts:
            ok = True
            for i, (mx, mz, mr) in enumerate(merged):
                if math.hypot(cx - mx, cz - mz) < 1.0 and abs(r - mr) < 1.0:
                    ok = False
                    break
            if ok:
                merged.append((cx, cz, r))

        merged.sort(key=lambda t: t[2], reverse=True)
        return merged

    # ---------------- Identify TOP/BOTTOM face clusters ----------------
    faces = list(shape.Faces())
    top_cands = []
    bot_cands = []

    for f in faces:
        if not _is_planar(f):
            continue
        n = _safe_normal(f)
        if n is None:
            continue
        if n.y > 0.95:
            top_cands.append((f, _area(f), f.Center().y))
        elif n.y < -0.95:
            bot_cands.append((f, _area(f), f.Center().y))

    top_cands.sort(key=lambda t: t[1], reverse=True)
    bot_cands.sort(key=lambda t: t[1], reverse=True)

    print(f"Planar +Y faces: {len(top_cands)}; planar -Y faces: {len(bot_cands)}")
    if not top_cands or not bot_cands:
        print("ERROR: Could not find suitable planar faces with normals ~±Y")
        return cq.Workplane(obj=shape)

    top_y_ref = top_cands[0][2]
    bot_y_ref = bot_cands[0][2]
    y_cluster_tol = 0.8

    top_faces = [f for (f, a, cy) in top_cands if abs(cy - top_y_ref) < y_cluster_tol and a > 50.0]
    bot_faces = [f for (f, a, cy) in bot_cands if abs(cy - bot_y_ref) < y_cluster_tol and a > 50.0]

    print(f"Top cluster @Y~{top_y_ref:.3f}: {len(top_faces)} faces")
    print(f"Bottom cluster @Y~{bot_y_ref:.3f}: {len(bot_faces)} faces")

    # ---------------- Slot pattern parameters (tuned to actually be a 2D pattern on narrow rails) ----------------
    slot_len = 22.0      # along Z direction
    slot_w = 5.0         # along X direction
    cut_depth = 2.0      # into solid
    edge_margin = 6.0    # keep away from outer edges

    pitch_z = slot_len + 14.0
    pitch_x = slot_w + 5.0     # tighter so we can get 2 columns if width allows

    def _cut_slots_on_face(base_wp, face, tag=""):
        fc = face.Center()
        fbb = face.BoundingBox()
        xSpan = fbb.xmax - fbb.xmin
        zSpan = fbb.zmax - fbb.zmin
        print(f"Face {tag}: centerY={fc.y:.3f} area={_area(face):.1f} xSpan={xSpan:.3f} zSpan={zSpan:.3f}")

        # Compute safe interior bounds for slot centers
        x0 = fbb.xmin + edge_margin + (slot_w / 2.0)
        x1 = fbb.xmax - edge_margin - (slot_w / 2.0)
        z0 = fbb.zmin + edge_margin + (slot_len / 2.0)
        z1 = fbb.zmax - edge_margin - (slot_len / 2.0)

        if x1 <= x0 or z1 <= z0:
            print(f"Face {tag}: insufficient room after margins; skipping")
            return base_wp

        # Prefer at least 2 columns when width supports it
        min_cols = 2 if (x1 - x0) >= (pitch_x + 0.5) else 1
        xs = _centered_coords(x0, x1, pitch_x, force_min_count=min_cols)
        zs = _centered_coords(z0, z1, pitch_z, force_min_count=1)

        plane = _build_plane_on_face(face)

        # Keepouts around holes/boss boundaries (inner wires)
        keep_pad = (slot_w / 2.0) + 6.0
        keepouts = _wire_keepouts_on_face(face, pad=keep_pad)
        if keepouts:
            print(f"Face {tag}: keepouts(innerWires)={len(keepouts)} (showing up to 6)")
            for i, (kx, kz, kr) in enumerate(keepouts[:6]):
                print(f"  keepout[{i}]: center=({kx:.2f},{kz:.2f}) r={kr:.2f}")

        pts_local = []
        skipped = 0
        for x in xs:
            for z in zs:
                blocked = False
                for (kx, kz, kr) in keepouts:
                    if math.hypot(x - kx, z - kz) < kr:
                        blocked = True
                        break
                if blocked:
                    skipped += 1
                    continue

                v_global = cq.Vector(x, fc.y, z)
                v_loc = plane.toLocalCoords(v_global)
                pts_local.append((v_loc.x, v_loc.y))

        print(f"Face {tag}: slot centers={len(pts_local)} (skipped {skipped}) cols={len(xs)} rows={len(zs)}")
        if not pts_local:
            return base_wp

        w = cq.Workplane(plane).pushPoints(pts_local)
        try:
            # with our plane choice, 90deg makes slot length align with global Z
            w = w.slot2D(slot_len, slot_w, angle=90)
        except TypeError:
            w = w.slot2D(slot_len, slot_w)

        cutters = w.extrude(-cut_depth, combine=False)
        try:
            return base_wp.cut(cutters)
        except Exception as e:
            print(f"ERROR cutting on face {tag}: {e}")
            return base_wp

    base = cq.Workplane(obj=shape)

    for i, f in enumerate(top_faces):
        base = _cut_slots_on_face(base, f, tag=f"TOP[{i}]")

    for i, f in enumerate(bot_faces):
        base = _cut_slots_on_face(base, f, tag=f"BOTTOM[{i}]")

    print("Done: slot patterns attempted on top and bottom face clusters.")
    return base
