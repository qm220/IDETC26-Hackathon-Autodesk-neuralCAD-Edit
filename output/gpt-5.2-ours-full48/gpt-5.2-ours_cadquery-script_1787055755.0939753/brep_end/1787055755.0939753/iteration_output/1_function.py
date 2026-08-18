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

    # --- Parameters from request ---
    depth_change = 10.0  # shallower by 10mm => move base +10mm in Z
    jaw_half = 10.0      # keep 20mm opening
    fillet_r = 5.0

    # --- Find existing slot base face (planar, normal ~±Z, most negative center.z among reasonable candidates) ---
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
            # Ignore tiny planes (e.g., pocket end walls)
            if a < 40.0:
                continue
            z_cands.append((i, a, c.x, c.y, c.z, n.z))
        except Exception:
            continue

    if not z_cands:
        raise ValueError("Could not find any sufficiently-large planar faces with normal approximately along Z.")

    # Prefer faces in the head region (more negative Z). The slot base is expected around Z≈-110.
    # Heuristic: pick the minimum center.z among candidates.
    base_pick = min(z_cands, key=lambda t: t[4])
    old_base_z = float(base_pick[4])
    print("Planar ~Z candidates (idx, area, cz, nz) [sorted by cz, first 10]:")
    for row in sorted(z_cands, key=lambda t: t[4])[:10]:
        print(f"  idx={row[0]:3d} A={row[1]:8.3f} cz={row[4]:9.3f} nz={row[5]: .3f}")
    print(f"Picked slot-base candidate: idx={base_pick[0]} old_base_z={old_base_z:.3f} mm")

    new_base_z = old_base_z + depth_change
    print(f"Target new_base_z = {new_base_z:.3f} mm (old + {depth_change})")

    # --- Robust booleans helpers ---
    eps = 0.2
    y0 = bbox.ymin - eps
    height_y = bbox.ylen + 2 * eps

    def make_box(xmin, xmax, zmin, zmax):
        dx = float(xmax - xmin)
        dz = float(zmax - zmin)
        return cq.Solid.makeBox(dx, float(height_y), dz, cq.Vector(float(xmin), float(y0), float(zmin)))

    def make_cyl_y(cx, cz, r):
        return cq.Solid.makeCylinder(float(r), float(height_y), cq.Vector(float(cx), float(y0), float(cz)), cq.Vector(0, 1, 0))

    # --- 1) Fill the deepest 10mm of the slot (shallower by 10mm) ---
    # Split fill into two regions to respect the old root fillet zone.
    zA0 = old_base_z - eps
    zA1 = old_base_z + fillet_r + eps
    zB0 = old_base_z + fillet_r - eps
    zB1 = new_base_z + eps

    plug_bottom = make_box(-(jaw_half + fillet_r), (jaw_half + fillet_r), zA0, zA1)
    plugs = cq.Workplane(obj=plug_bottom)
    if zB1 > zB0 + 1e-6:
        plug_top = make_box(-jaw_half, jaw_half, zB0, zB1)
        plugs = plugs.union(plug_top)

    model_filled = wp.union(plugs)

    # --- 2) Recreate the internal root fillets at the new base (r=5) ---
    zC0 = new_base_z - eps
    zC1 = new_base_z + fillet_r + eps

    def corner_removal(side):
        # side = +1 right, -1 left
        if side > 0:
            x0, x1 = jaw_half, jaw_half + fillet_r
            cx = jaw_half + fillet_r
        else:
            x0, x1 = -(jaw_half + fillet_r), -jaw_half
            cx = -(jaw_half + fillet_r)
        cz = new_base_z + fillet_r

        corner_box = make_box(x0, x1, zC0, zC1)
        cyl = make_cyl_y(cx, cz, fillet_r)
        quarter_keep = cq.Workplane(obj=cyl).intersect(corner_box)
        removal = cq.Workplane(obj=corner_box).cut(quarter_keep)
        return removal

    result = model_filled.cut(corner_removal(+1)).cut(corner_removal(-1))

    # --- Validation prints (to judge correctness) ---
    res = result.val()
    rb = res.BoundingBox()

    # Find planar face closest to new_base_z with normal ~-Z (slot base expected to face -Z)
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
        print("Post-edit: WARNING: no planar ~Z faces found for base verification")

    # Find jaw inner faces: planar with normal ~±X, and extending to mouth at zmin (~-150)
    jaw_cands = []
    for f in res.Faces():
        try:
            if f.geomType() != "PLANE":
                continue
            n = f.normalAt()
            if abs(n.x) < 0.95:
                continue
            fb = f.BoundingBox()
            # Must reach close to the mouth at far negative z
            if fb.zmin > rb.zmin + 2.0:
                continue
            c = f.Center()
            jaw_cands.append((c.x, c.z, n.x, f.Area(), fb.zmin, fb.zmax))
        except Exception:
            continue

    if jaw_cands:
        # pick the most positive-x and most negative-x among these as jaw faces
        right = max(jaw_cands, key=lambda t: t[0])
        left = min(jaw_cands, key=lambda t: t[0])
        opening = float(right[0] - left[0])
        print(f"Post-edit jaw candidates: count={len(jaw_cands)}")
        print(f"  Left jaw:  cx={left[0]:.3f}, cz={left[1]:.3f}, nx={left[2]:.3f}, A={left[3]:.3f}, zrange=({left[4]:.3f},{left[5]:.3f})")
        print(f"  Right jaw: cx={right[0]:.3f}, cz={right[1]:.3f}, nx={right[2]:.3f}, A={right[3]:.3f}, zrange=({right[4]:.3f},{right[5]:.3f})")
        print(f"  Measured jaw opening (center-to-center in X) ≈ {opening:.3f} mm (target 20.000 mm)")
    else:
        print("Post-edit: WARNING: could not robustly identify jaw inner faces for opening verification")

    print("Edit applied: slot base moved +10mm in Z (shallower) and geometry trimmed to preserve r=5 root fillets; jaw opening intended to remain 20mm.")
    return result
