def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args.get("input_file", ""))
    if not input_file or not os.path.exists(input_file):
        raise ValueError(f"Input STEP file not found: {input_file}")

    wp = cq.importers.importStep(input_file)
    shp = wp.val()

    bbox = shp.BoundingBox()
    print(f"Loaded STEP: {input_file}")
    print(f"Valid: {shp.isValid()}")
    print(f"Faces: {len(shp.Faces())}")
    print(f"BBOX: xmin={bbox.xmin:.3f}, xmax={bbox.xmax:.3f}, ymin={bbox.ymin:.3f}, ymax={bbox.ymax:.3f}, zmin={bbox.zmin:.3f}, zmax={bbox.zmax:.3f}")

    # --- User request ---
    depth_shallower = 10.0  # reduce slot depth by 10mm
    fillet_r = 5.0

    # --- Helpers ---
    eps = 0.2
    y0 = bbox.ymin - eps
    height_y = bbox.ylen + 2 * eps

    def make_box(xmin, xmax, zmin, zmax):
        dx = float(xmax - xmin)
        dz = float(zmax - zmin)
        return cq.Solid.makeBox(dx, float(height_y), dz, cq.Vector(float(xmin), float(y0), float(zmin)))

    def make_cyl_y(cx, cz, r):
        return cq.Solid.makeCylinder(float(r), float(height_y), cq.Vector(float(cx), float(y0), float(cz)), cq.Vector(0, 1, 0))

    # --- Identify jaw faces to get jaw opening and jaw_half robustly ---
    jaw_cands = []
    for f in shp.Faces():
        try:
            if f.geomType() != "PLANE":
                continue
            n = f.normalAt()
            if abs(n.x) < 0.95:
                continue
            fb = f.BoundingBox()
            # slot jaw faces reach the mouth at far end (bbox.zmin)
            if fb.zmin > bbox.zmin + 2.0:
                continue
            a = f.Area()
            if a < 200.0:
                continue
            c = f.Center()
            jaw_cands.append((c.x, c.z, n.x, a, fb.zmin, fb.zmax))
        except Exception:
            continue

    if len(jaw_cands) < 2:
        raise ValueError("Could not robustly identify the two jaw inner faces.")

    right = max(jaw_cands, key=lambda t: t[0])
    left = min(jaw_cands, key=lambda t: t[0])
    jaw_opening = float(right[0] - left[0])
    jaw_half = 0.5 * jaw_opening

    print(f"Detected jaw faces:")
    print(f"  Left jaw:  cx={left[0]:.3f}, zrange=({left[4]:.3f},{left[5]:.3f}), area={left[3]:.3f}")
    print(f"  Right jaw: cx={right[0]:.3f}, zrange=({right[4]:.3f},{right[5]:.3f}), area={right[3]:.3f}")
    print(f"Detected jaw opening = {jaw_opening:.3f} mm (target to keep: 20mm)")

    # --- Find existing slot base face (planar, normal ~±Z, in head region, area ~150 typical) ---
    z_cands = []
    for i, f in enumerate(shp.Faces()):
        try:
            if f.geomType() != "PLANE":
                continue
            n = f.normalAt()
            if abs(n.z) < 0.95:
                continue
            c = f.Center()
            a = f.Area()
            # slot base face is relatively small-ish but not tiny
            if a < 60.0 or a > 600.0:
                continue
            # should be in head region (negative Z for this model), closer to mouth than ring
            if c.z > (bbox.zmin + 0.65 * (bbox.zmax - bbox.zmin)):
                continue
            z_cands.append((i, a, c.z, n.z))
        except Exception:
            continue

    if not z_cands:
        raise ValueError("Could not find candidate planar ~Z faces for the slot base.")

    # Heuristic: pick the candidate closest to the jaw-face zmax (where fillets meet), shifted by +fillet_r toward handle.
    # In the current model, jaw faces end around base +/- fillet_r.
    jaw_end_z_est = 0.5 * (left[5] + right[5])  # zmax of jaws

    def score_base(cz):
        # base is about jaw_end_z_est + sign*fillet_r, but we don't know sign, so just use distance to cz and cz+/-r
        return min(abs(cz - (jaw_end_z_est + fillet_r)), abs(cz - (jaw_end_z_est - fillet_r)), abs(cz - jaw_end_z_est))

    base_pick = min(z_cands, key=lambda t: score_base(t[2]))
    old_base_z = float(base_pick[2])
    print("Planar ~Z base candidates (idx, area, cz, nz):")
    for row in sorted(z_cands, key=lambda t: t[2])[:10]:
        print(f"  idx={row[0]:3d} A={row[1]:8.3f} cz={row[2]:9.3f} nz={row[3]: .3f}")
    print(f"Picked slot-base candidate: idx={base_pick[0]} old_base_z={old_base_z:.3f} mm")

    # Determine which direction is 'toward the opening/mouth'
    mouth_z = float(bbox.zmin)
    # If mouth is more negative than base, moving base toward mouth means decreasing Z.
    toward_mouth_sign = -1.0 if mouth_z < old_base_z else 1.0

    new_base_z = old_base_z + toward_mouth_sign * depth_shallower
    print(f"Mouth z={mouth_z:.3f}, toward_mouth_sign={toward_mouth_sign:+.0f}")
    print(f"Target new_base_z={new_base_z:.3f} (shallower by {depth_shallower}mm)")

    # Safety: ensure we don't push base beyond mouth
    if toward_mouth_sign < 0 and new_base_z < mouth_z + fillet_r + 1.0:
        raise ValueError("Requested shallowing would move the base too close to / past the mouth.")
    if toward_mouth_sign > 0 and new_base_z > mouth_z - fillet_r - 1.0:
        raise ValueError("Requested shallowing would move the base too close to / past the mouth (sign case).")

    # --- 1) Fill the portion of the slot that should no longer be cut (between new base and old base) ---
    z_fill0 = min(new_base_z, old_base_z) - eps
    z_fill1 = max(new_base_z, old_base_z) + eps

    plug = make_box(-(jaw_half + fillet_r), (jaw_half + fillet_r), z_fill0, z_fill1)
    model_filled = wp.union(cq.Workplane(obj=plug))

    # --- 2) Recreate the internal root fillets at the NEW base (cut quarter-cylinders from the solid) ---
    # Fillet zone spans from new_base_z toward mouth by fillet_r
    z_center = new_base_z + toward_mouth_sign * fillet_r
    z_f0 = min(new_base_z, z_center) - eps
    z_f1 = max(new_base_z, z_center) + eps

    def fillet_corner_cut(side):
        # side: +1 right, -1 left
        if side > 0:
            x0, x1 = jaw_half, jaw_half + fillet_r
            cx = jaw_half + fillet_r
        else:
            x0, x1 = -(jaw_half + fillet_r), -jaw_half
            cx = -(jaw_half + fillet_r)

        cyl = make_cyl_y(cx, z_center, fillet_r)
        corner_box = make_box(x0, x1, z_f0, z_f1)
        quarter = cq.Workplane(obj=cyl).intersect(corner_box)
        return quarter

    # Cut away material to form the cavity fillets (increase the void at the corner)
    result = model_filled.cut(fillet_corner_cut(+1)).cut(fillet_corner_cut(-1))

    # --- Validation prints ---
    res = result.val()
    rb = res.BoundingBox()

    # Base verification: find planar ~Z face closest to new_base_z
    base_faces = []
    for f in res.Faces():
        try:
            if f.geomType() != "PLANE":
                continue
            n = f.normalAt()
            if abs(n.z) < 0.95:
                continue
            c = f.Center()
            a = f.Area()
            base_faces.append((abs(c.z - new_base_z), c.z, n.z, a))
        except Exception:
            continue

    if base_faces:
        best = min(base_faces, key=lambda t: t[0])
        print(f"Post-edit: closest planar ~Z face to new_base_z: cz={best[1]:.3f}, nz={best[2]:.3f}, area={best[3]:.3f}, |dz|={best[0]:.3f}")
    else:
        print("Post-edit: WARNING: no planar ~Z faces found")

    # Jaw verification: detect jaw faces again and report opening and zmax (should move toward mouth by ~10mm)
    jaw2 = []
    for f in res.Faces():
        try:
            if f.geomType() != "PLANE":
                continue
            n = f.normalAt()
            if abs(n.x) < 0.95:
                continue
            fb = f.BoundingBox()
            if fb.zmin > rb.zmin + 2.0:
                continue
            a = f.Area()
            if a < 200.0:
                continue
            c = f.Center()
            jaw2.append((c.x, a, fb.zmin, fb.zmax))
        except Exception:
            continue

    if len(jaw2) >= 2:
        r2 = max(jaw2, key=lambda t: t[0])
        l2 = min(jaw2, key=lambda t: t[0])
        opening2 = float(r2[0] - l2[0])
        print(f"Post-edit jaw opening = {opening2:.3f} mm (should remain {jaw_opening:.3f} mm, nominal 20mm)")
        print(f"Post-edit jaw zmax (left,right) = ({l2[3]:.3f}, {r2[3]:.3f}) ; expected approx {new_base_z + toward_mouth_sign * fillet_r:.3f} (fillet start)")
    else:
        print("Post-edit: WARNING: could not re-identify jaw faces")

    print("Edit applied: slot base moved toward the mouth by 10mm (shallower), jaw opening preserved by not moving jaw planes.")
    return result
