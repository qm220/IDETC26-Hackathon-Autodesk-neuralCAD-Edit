def my_cad_function(args):
    import os
    import cadquery as cq

    # --- Load model ---
    input_file = os.path.expanduser(args.get("input_file", ""))
    if not input_file or not os.path.exists(input_file):
        raise ValueError(f"Input STEP file not found: {input_file}")

    model_wp = cq.importers.importStep(input_file)
    shp = model_wp.val()

    # --- Basic diagnostics ---
    bbox = shp.BoundingBox()
    print(f"Loaded STEP: {input_file}")
    print(f"Valid: {shp.isValid()}")
    print(f"Faces: {len(shp.Faces())}")
    print(f"BBOX: xmin={bbox.xmin:.3f}, xmax={bbox.xmax:.3f}, ymin={bbox.ymin:.3f}, ymax={bbox.ymax:.3f}, zmin={bbox.zmin:.3f}, zmax={bbox.zmax:.3f}")
    print(f"Size: dx={bbox.xlen:.3f}, dy={bbox.ylen:.3f}, dz={bbox.zlen:.3f}")

    # --- Find the slot base face (planar face with normal ~±Z and large area) ---
    cands = []
    faces = shp.Faces()
    for i, f in enumerate(faces):
        try:
            if f.geomType() != "PLANE":
                continue
            n = f.normalAt()
            if abs(n.z) < 0.95:
                continue
            a = f.Area()
            c = f.Center()
            cands.append((i, a, c.x, c.y, c.z, n.x, n.y, n.z))
        except Exception:
            continue

    cands_sorted = sorted(cands, key=lambda t: t[4])  # sort by center.z
    print("Planar faces with normal ~Z (idx, area, cx, cy, cz, nz) [first 20 by cz]:")
    for row in cands_sorted[:20]:
        i, a, cx, cy, cz, nx, ny, nz = row
        print(f"  {i:4d}: A={a:9.3f}, C=({cx:7.3f},{cy:7.3f},{cz:8.3f}), nz={nz: .3f}")

    if not cands:
        raise ValueError("Could not find any planar faces with normal approximately along Z to infer slot base.")

    # Prefer large-area faces (slot base is through-thickness, typically large area)
    large = [t for t in cands if t[1] > 200.0]
    pick_pool = large if large else cands

    # Heuristic: slot base is likely the most negative-Z among these candidates
    base_pick = min(pick_pool, key=lambda t: t[4])
    old_base_z = float(base_pick[4])
    print(f"Picked slot-base candidate face idx={base_pick[0]} at old_base_z={old_base_z:.3f} mm")

    # --- Parameters from task ---
    depth_change = 10.0  # make shallower by 10 mm
    jaw_half = 10.0      # keep 20 mm opening (X=±10)
    fillet_r = 5.0

    # Following the task plan: move slot base +10mm in Z
    new_base_z = old_base_z + depth_change
    print(f"New target slot base z = {new_base_z:.3f} (old + {depth_change})")

    # --- Build geometry helpers ---
    eps = 0.2  # boolean robustness
    y0 = bbox.ymin - eps
    height_y = bbox.ylen + 2 * eps

    def make_box(xmin, xmax, zmin, zmax):
        dx = float(xmax - xmin)
        dz = float(zmax - zmin)
        return cq.Solid.makeBox(dx, float(height_y), dz, cq.Vector(float(xmin), float(y0), float(zmin)))

    def make_cyl_y(cx, cz, r):
        # Cylinder along +Y, base center at (cx, y0, cz)
        return cq.Solid.makeCylinder(float(r), float(height_y), cq.Vector(float(cx), float(y0), float(cz)), cq.Vector(0, 1, 0))

    # --- 1) Fill the deepest 10mm of the existing slot (make it shallower) ---
    # We fill in two slabs:
    #   a) a wider slab for the old root fillet zone (z in [old_base_z, old_base_z+R])
    #   b) a narrower slab for the remaining part up to new_base_z (z in [old_base_z+R, new_base_z])
    # This avoids adding material outside the head as much as possible.
    zA0 = old_base_z - eps
    zA1 = old_base_z + fillet_r + eps
    zB0 = old_base_z + fillet_r - eps
    zB1 = new_base_z + eps

    plug_bottom = make_box(-(jaw_half + fillet_r), (jaw_half + fillet_r), zA0, zA1)
    plug_top = None
    if zB1 > zB0 + 1e-6:
        plug_top = make_box(-jaw_half, jaw_half, zB0, zB1)

    plug_wp = cq.Workplane(obj=plug_bottom)
    if plug_top is not None:
        plug_wp = plug_wp.union(plug_top)

    model_filled = model_wp.union(plug_wp)

    # --- 2) Recreate the new root fillets at the new base (r=5) without changing jaw opening ---
    # We remove only the corner material in the region:
    #   x in [10,15] and z in [new_base_z, new_base_z+5] (and mirrored on left)
    # but *excluding* the quarter-cylinder region that should remain as the fillet surface.
    zC0 = new_base_z - eps
    zC1 = new_base_z + fillet_r + eps

    def corner_removal(side):
        # side = +1 (right) or -1 (left)
        if side > 0:
            x0, x1 = jaw_half, jaw_half + fillet_r
            cx = jaw_half + fillet_r
        else:
            x0, x1 = -(jaw_half + fillet_r), -jaw_half
            cx = -(jaw_half + fillet_r)
        cz = new_base_z + fillet_r

        corner_box = make_box(x0, x1, zC0, zC1)
        cyl = make_cyl_y(cx, cz, fillet_r)

        # quarter-cylinder region INSIDE the corner box (this is the material that should remain)
        quarter_keep_wp = cq.Workplane(obj=cyl).intersect(corner_box)

        # removal volume = corner_box - quarter_keep
        removal_wp = cq.Workplane(obj=corner_box).cut(quarter_keep_wp)
        return removal_wp

    cut_r = corner_removal(+1)
    cut_l = corner_removal(-1)

    result = model_filled.cut(cut_r).cut(cut_l)

    print("Edit applied: slot made shallower by +10mm in Z at the base; jaw opening planes intended to remain at X=±10.")
    return result
