def my_cad_function(args):
    import cadquery as cq
    import os
    
    input_file = args.get("input_file", None)
    if not input_file or not os.path.exists(os.path.expanduser(input_file)):
        raise ValueError(f"Missing or invalid args['input_file']: {input_file}")
    input_file = os.path.expanduser(input_file)

    model_wp = cq.importers.importStep(input_file)
    solid = model_wp.val() if hasattr(model_wp, "val") else model_wp

    bb = solid.BoundingBox()
    dx, dy, dz = (bb.xmax - bb.xmin), (bb.ymax - bb.ymin), (bb.zmax - bb.zmin)
    max_dim = max(dx, dy, dz)

    # STEP unit heuristic only for converting requested 1.5mm
    scale_mm_to_model = 0.001 if max_dim < 10 else 1.0
    rib_t = 1.5 * scale_mm_to_model

    print("=== Loaded model ===")
    print(f"BBox: x[{bb.xmin:.6f},{bb.xmax:.6f}] y[{bb.ymin:.6f},{bb.ymax:.6f}] z[{bb.zmin:.6f},{bb.zmax:.6f}]")
    print(f"Dims: dx={dx:.6f}, dy={dy:.6f}, dz={dz:.6f}, max_dim={max_dim:.6f}")
    print(f"Assumed mm_to_model scale: {scale_mm_to_model} => rib thickness in model units: {rib_t:.6f}")

    # --- Find near-horizontal planar faces (normal ~ +/-Y) ---
    faces = solid.Faces()
    horiz = []
    for f in faces:
        try:
            if f.geomType() != "PLANE":
                continue
            n = f.normalAt()
            if abs(n.y) < 0.95:
                continue
            c = f.Center()
            horiz.append((f, f.Area(), c.y, n.y, c))
        except Exception:
            continue

    if not horiz:
        raise ValueError("No near-horizontal planar faces found; cannot locate pocket floor.")

    horiz.sort(key=lambda it: it[2])  # by center.y

    print(f"Horizontal planar face candidates (count={len(horiz)}), lowest 12 by center.y:")
    for i, (f, a, y, ny, c) in enumerate(horiz[:12]):
        print(f"  idx={i:02d} y={y:.6f} ny={ny:+.3f} area={a:.6f} center=({c.x:.3f},{c.y:.3f},{c.z:.3f})")

    # Choose pocket floor as the lowest significant planar face above the global bottom
    bottom_face, bottom_area, bottom_y, bottom_ny, bottom_c = horiz[0]
    tol_y = 1e-6 * max_dim

    pocket_floor = None
    for (f, a, y, ny, c) in horiz[1:]:
        if y <= bottom_y + tol_y:
            continue
        if y > bb.ymin + 0.50 * dy:
            continue
        if a < 0.02 * bottom_area:
            continue
        pocket_floor = (f, a, y, ny, c)
        break
    if pocket_floor is None:
        pocket_floor = horiz[1]

    floor_face, floor_area, floor_y, floor_ny, floor_c = pocket_floor
    floor_bb = floor_face.BoundingBox()
    n = floor_face.normalAt()

    print("=== Chosen pocket floor face ===")
    print(f"floor_y={floor_y:.6f} area={floor_area:.6f} center=({floor_c.x:.6f},{floor_c.y:.6f},{floor_c.z:.6f})")
    print(f"floor_normal=({n.x:.3f},{n.y:.3f},{n.z:.3f})")
    print(f"floor_face_bb: x[{floor_bb.xmin:.6f},{floor_bb.xmax:.6f}] z[{floor_bb.zmin:.6f},{floor_bb.zmax:.6f}]")

    # Decide extrusion direction: for a cavity face, outward normal should point into void.
    # Validate by probing a bit into each side; the solid-side should return isInside=True.
    tol_inside = 1e-7 * max_dim if max_dim > 0 else 1e-7
    eps_in = max(0.50 * scale_mm_to_model, 1e-3 * max_dim)  # ~0.5mm or scaled

    def _inside(v):
        try:
            return bool(solid.isInside(v, tol_inside))
        except Exception:
            return None

    p_plus = cq.Vector(floor_c.x + n.x * eps_in, floor_c.y + n.y * eps_in, floor_c.z + n.z * eps_in)
    p_minus = cq.Vector(floor_c.x - n.x * eps_in, floor_c.y - n.y * eps_in, floor_c.z - n.z * eps_in)
    inside_plus = _inside(p_plus)
    inside_minus = _inside(p_minus)

    # If minus is inside, normal points into void (good). If plus is inside, invert.
    invert = False
    if inside_minus is True and inside_plus is not True:
        invert = False
    elif inside_plus is True and inside_minus is not True:
        invert = True
    else:
        # fallback heuristic: prefer extruding upward (+Y) from this internal face
        invert = (n.y < 0)

    print("=== Direction probe (for workplane invert) ===")
    print(f"eps_in={eps_in:.6f} inside_plus={inside_plus} inside_minus={inside_minus} => invert={invert}")

    # Rib length: along global X, keep margins to avoid end fillet/transition regions
    face_xspan = max(1e-9, (floor_bb.xmax - floor_bb.xmin))
    x_margin = max(0.12 * face_xspan, 3.0 * scale_mm_to_model)  # ~12% or ~3mm
    L = max(0.0, face_xspan - 2.0 * x_margin)
    if L <= 1e-6 * max_dim:
        L = 0.60 * dx

    print("=== Rib parameters ===")
    print(f"rib_thickness={rib_t:.6f}, rib_length={L:.6f}, x_margin={x_margin:.6f}")

    # Build the rib in-context on the selected face.
    # IMPORTANT: do NOT .add(floor_face) to a workplane that already contains the solid,
    # because that leaves multiple objects on the stack and workplane() will fail.
    sel = cq.selectors.NearestToPointSelector((floor_c.x, floor_c.y, floor_c.z))
    base = cq.Workplane(obj=solid).faces(sel)

    fvals = base.vals()
    print(f"NearestToPoint face selection count: {len(fvals)}")

    if len(fvals) != 1:
        # Reduce to a single best candidate: planar, |ny| high, closest y to floor_y, largest area
        cand = []
        for ff in fvals:
            try:
                if ff.geomType() != "PLANE":
                    continue
                nn = ff.normalAt()
                if abs(nn.y) < 0.95:
                    continue
                cc = ff.Center()
                cand.append((abs(cc.y - floor_y), -ff.Area(), ff))
            except Exception:
                continue
        if not cand:
            raise ValueError("Face selection near pocket floor returned multiple/non-planar faces; cannot safely place rib.")
        cand.sort(key=lambda t: (t[0], t[1]))
        chosen = cand[0][2]
        base = cq.Workplane(obj=solid).newObject([chosen])
        print("Reduced selection to a single planar face candidate.")

    wp = base.workplane(centerOption="CenterOfBoundBox", invert=invert)

    # Choose which in-plane axis is most aligned with global X, and orient rectangle accordingly
    xd = wp.plane.xDir
    yd = wp.plane.yDir
    x_align = abs(xd.x)
    y_align = abs(yd.x)

    if x_align >= y_align:
        dimx, dimy = L, rib_t
        axis_note = "L along WP x-axis"
    else:
        dimx, dimy = rib_t, L
        axis_note = "L along WP y-axis"

    print(f"Workplane axes alignment: |xd·X|={x_align:.3f}, |yd·X|={y_align:.3f} => {axis_note}")

    # Prefer 'until=next' so the rib terminates at the first intersected internal face.
    try:
        result = wp.rect(dimx, dimy, centered=True).extrude(until="next", combine=True)
        print("Rib extrude used until='next'.")
    except Exception as e1:
        print(f"Rib extrude until='next' failed: {e1}")

        # Fallback: estimate a safe height by ray sampling for first re-entry into solid.
        # If that fails, use a conservative height that should remain internal.
        void_dir = wp.plane.zDir  # extrusion direction (workplane normal)
        # start slightly off the face into the void
        eps0 = max(0.20 * scale_mm_to_model, 5e-4 * max_dim)
        start = cq.Vector(floor_c.x + void_dir.x * eps0, floor_c.y + void_dir.y * eps0, floor_c.z + void_dir.z * eps0)

        step = max(0.25 * scale_mm_to_model, 1e-3 * max_dim)
        max_scan = 0.60 * dy if dy > 0 else 0.60 * max_dim
        nsteps = int(max(10, min(400, max_scan / step)))

        hit_d = None
        last_out = None
        for i in range(1, nsteps + 1):
            p = cq.Vector(start.x + void_dir.x * step * i, start.y + void_dir.y * step * i, start.z + void_dir.z * step * i)
            inside = _inside(p)
            if inside is False:
                last_out = p
                continue
            if inside is True:
                hit_d = step * i
                break

        if hit_d is not None:
            h = max(0.5 * rib_t, hit_d - eps0 - 0.10 * scale_mm_to_model)
            print(f"Ray-scan found limiting solid at d~{hit_d:.6f} => using h={h:.6f}")
        else:
            h = min(0.35 * dy, 6.0 * scale_mm_to_model)
            h = max(h, 1.5 * rib_t)
            print(f"Ray-scan did not find a limiting face; using conservative blind h={h:.6f}")

        result = wp.rect(dimx, dimy, centered=True).extrude(h, combine=True)

    print("=== Done ===")
    return result
