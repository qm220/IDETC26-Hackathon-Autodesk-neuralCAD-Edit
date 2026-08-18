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

    # Heuristic for STEP units (mm vs m) just for reference prints
    # (We will model in the same native units; only the requested 1.5mm needs scaling if model is in meters.)
    # If the entire part is only ~0.1..1.0 units long, assume meters.
    scale_mm_to_model = 0.001 if max_dim < 10 else 1.0
    rib_t = 1.5 * scale_mm_to_model

    print("=== Loaded model ===")
    print(f"BBox: x[{bb.xmin:.6f},{bb.xmax:.6f}] y[{bb.ymin:.6f},{bb.ymax:.6f}] z[{bb.zmin:.6f},{bb.zmax:.6f}]")
    print(f"Dims: dx={dx:.6f}, dy={dy:.6f}, dz={dz:.6f}, max_dim={max_dim:.6f}")
    print(f"Assumed mm_to_model scale: {scale_mm_to_model} => rib thickness in model units: {rib_t:.6f}")

    # --- Find candidate horizontal planar faces (normal ~ +/-Y), then choose a likely pocket floor ---
    faces = solid.Faces()
    horiz = []
    for f in faces:
        try:
            if f.geomType() != "PLANE":
                continue
            n = f.normalAt()
            if abs(n.y) < 0.90:
                continue
            c = f.Center()
            horiz.append((f, f.Area(), c.y, n.y, c))
        except Exception:
            continue

    horiz.sort(key=lambda it: it[2])  # sort by center.y
    print(f"Horizontal planar face candidates (count={len(horiz)}), lowest 8 by center.y:")
    for i, (f, a, y, ny, c) in enumerate(horiz[:8]):
        print(f"  idx={i:02d} y={y:.6f} ny={ny:+.3f} area={a:.6f} center=({c.x:.3f},{c.y:.3f},{c.z:.3f})")

    # Choose a candidate "pocket floor":
    # - not the absolute bottom-most horizontal plane
    # - in the lower portion of the part
    # - relatively large area
    y_low = bb.ymin + 0.02 * dy
    y_high = bb.ymin + 0.70 * dy

    candidates = [(f, a, y, ny, c) for (f, a, y, ny, c) in horiz if (y > y_low and y < y_high)]
    # Exclude the very bottom-most (within small tolerance)
    if horiz:
        bottom_y = horiz[0][2]
        candidates = [(f, a, y, ny, c) for (f, a, y, ny, c) in candidates if (y > bottom_y + 1e-6 * max_dim)]

    if not candidates:
        # fallback: use second-lowest horizontal planar face if available
        if len(horiz) >= 2:
            floor_face, _, _, _, _ = horiz[1]
        elif len(horiz) == 1:
            floor_face = horiz[0][0]
        else:
            raise ValueError("No horizontal planar faces found; cannot place rib.")
    else:
        # prefer largest area among candidates
        floor_face = max(candidates, key=lambda it: it[1])[0]

    floor_c = floor_face.Center()
    floor_bb = floor_face.BoundingBox()

    print("=== Chosen reference face (pocket floor candidate) ===")
    print(f"floor_center=({floor_c.x:.6f},{floor_c.y:.6f},{floor_c.z:.6f})")
    print(f"floor_face_bb: x[{floor_bb.xmin:.6f},{floor_bb.xmax:.6f}] z[{floor_bb.zmin:.6f},{floor_bb.zmax:.6f}]")

    # Decide extrusion direction by checking if a point slightly offset along +Y is inside solid.
    eps = 1e-4 * max_dim if max_dim > 0 else 1e-3
    test_up = cq.Vector(floor_c.x, floor_c.y + eps, floor_c.z)
    test_dn = cq.Vector(floor_c.x, floor_c.y - eps, floor_c.z)

    def _is_inside(vec):
        try:
            return bool(solid.isInside(vec, 1e-6 * max_dim))
        except Exception:
            # If isInside isn't available, assume +Y is towards pocket (best guess)
            return False

    up_inside = _is_inside(test_up)
    dn_inside = _is_inside(test_dn)
    # We want to extrude into "void" (outside the solid) starting from the internal face.
    # If +Y is inside solid, then extrude -Y; otherwise extrude +Y.
    extrude_sign = -1.0 if up_inside and (not dn_inside) else 1.0

    print("=== Extrusion direction test ===")
    print(f"test_up inside? {up_inside} ; test_dn inside? {dn_inside} ; extrude_sign={extrude_sign:+.0f} (normal=(0,{extrude_sign:+.0f},0))")

    # Rib extents inside face bounding box (trim back from ends)
    x_margin = 0.10 * (floor_bb.xmax - floor_bb.xmin)
    if x_margin <= 0:
        x_margin = 0.05 * dx
    L = max(0.0, (floor_bb.xmax - floor_bb.xmin) - 2.0 * x_margin)

    # If L is tiny, fallback to a fraction of overall part length
    if L <= 1e-6 * max_dim:
        L = 0.60 * dx

    # Place at mid-width within the pocket floor face bbox
    cx = 0.5 * (floor_bb.xmin + floor_bb.xmax)
    cz = 0.5 * (floor_bb.zmin + floor_bb.zmax)
    y0 = floor_c.y

    print("=== Rib sketch parameters ===")
    print(f"rib_length L={L:.6f}, rib_thickness t={rib_t:.6f}, at (cx, y0, cz)=({cx:.6f},{y0:.6f},{cz:.6f})")

    # Create rib solid: thin rectangle extruded normal to floor plane, aiming 'until next' face.
    # Use a world-aligned plane to guarantee longitudinal along global X and thickness along global Z.
    plane = cq.Plane(origin=(0, y0, 0), xDir=(1, 0, 0), normal=(0, extrude_sign, 0))
    rib_wp = cq.Workplane(plane).center(cx, cz).rect(L, rib_t, centered=True)

    rib_solid = None
    # Try up-to-next if supported
    try:
        rib_solid = rib_wp.extrude(until="next", combine=False)
        print("Rib extrude used until='next'.")
    except Exception as e1:
        # Fallback: blind extrude with conservative height
        h = 0.25 * dy if dy > 0 else (0.25 * max_dim)
        if h <= 0:
            h = 10.0 * scale_mm_to_model
        try:
            rib_solid = rib_wp.extrude(h, combine=False)
            print(f"Rib extrude fallback used blind height={h:.6f} due to: {e1}")
        except Exception as e2:
            print("Failed to create rib solid.")
            raise

    # Join rib to original model
    try:
        result = cq.Workplane(obj=solid).union(rib_solid)
    except Exception:
        # Sometimes union expects shapes
        result = model_wp.union(rib_solid)

    print("=== Done (first iteration) ===")
    return result
