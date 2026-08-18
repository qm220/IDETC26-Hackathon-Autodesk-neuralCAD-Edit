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

    # --- Find horizontal-ish planar faces (normal ~ +/-Y) ---
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

    print(f"Horizontal planar face candidates (count={len(horiz)}), lowest 10 by center.y:")
    for i, (f, a, y, ny, c) in enumerate(horiz[:10]):
        print(f"  idx={i:02d} y={y:.6f} ny={ny:+.3f} area={a:.6f} center=({c.x:.3f},{c.y:.3f},{c.z:.3f})")

    # Choose pocket floor as the second-lowest significant planar face (the one just above the global bottom).
    # This specifically targets the internal shelf plane around y~0.19 from planning (face_code 0003).
    bottom_face, bottom_area, bottom_y, bottom_ny, bottom_c = horiz[0]
    tol_y = 1e-6 * max_dim

    # Prefer the lowest face above bottom with a reasonably large area.
    pocket_floor = None
    for (f, a, y, ny, c) in horiz[1:]:
        if y <= bottom_y + tol_y:
            continue
        # require it to be in the lower half and not a tiny pad face
        if y > bb.ymin + 0.50 * dy:
            continue
        if a < 0.02 * bottom_area:  # exclude tiny planar features
            continue
        pocket_floor = (f, a, y, ny, c)
        break

    if pocket_floor is None:
        # fallback: simply take the second-lowest
        pocket_floor = horiz[1]

    floor_face, floor_area, floor_y, floor_ny, floor_c = pocket_floor
    floor_bb = floor_face.BoundingBox()

    print("=== Chosen pocket floor face ===")
    print(f"floor_y={floor_y:.6f} area={floor_area:.6f} center=({floor_c.x:.6f},{floor_c.y:.6f},{floor_c.z:.6f})")
    print(f"floor_face_bb: x[{floor_bb.xmin:.6f},{floor_bb.xmax:.6f}] z[{floor_bb.zmin:.6f},{floor_bb.zmax:.6f}]")

    # Determine which side of the floor face is the pocket void by probing inside/outside
    eps = 1e-4 * max_dim if max_dim > 0 else 1e-3
    n = floor_face.normalAt()

    def _is_inside(vec):
        try:
            return bool(solid.isInside(vec, 1e-7 * max_dim))
        except Exception:
            return None

    p_plus = cq.Vector(floor_c.x + n.x * eps, floor_c.y + n.y * eps, floor_c.z + n.z * eps)
    p_minus = cq.Vector(floor_c.x - n.x * eps, floor_c.y - n.y * eps, floor_c.z - n.z * eps)
    inside_plus = _is_inside(p_plus)
    inside_minus = _is_inside(p_minus)

    # We want to extrude into void (outside solid). If a probe is not inside => that side is void.
    outside_plus = (inside_plus is False)
    outside_minus = (inside_minus is False)

    # Determine whether to invert the workplane (flip normal) so that positive extrude goes into void.
    # If both sides appear outside (rare/degenerate), prefer the direction with +Y component (towards internal roof)
    invert = False
    if outside_plus and not outside_minus:
        invert = False
    elif outside_minus and not outside_plus:
        invert = True
    elif outside_plus and outside_minus:
        # choose direction more aligned with +Y (to avoid punching out the global bottom)
        invert = True if (-n.y) > (n.y) else False
    else:
        # If isInside unavailable/ambiguous, assume pocket void is upward (+Y) from this internal shelf
        invert = False

    print("=== Void-side probe & direction ===")
    print(f"face_normal=({n.x:.3f},{n.y:.3f},{n.z:.3f}) inside_plus={inside_plus} inside_minus={inside_minus} => invert={invert}")

    # Rib dimensions: long along global X, thin across width.
    face_xspan = max(1e-9, (floor_bb.xmax - floor_bb.xmin))
    x_margin = 0.12 * face_xspan
    L = max(0.0, face_xspan - 2.0 * x_margin)
    if L <= 1e-6 * max_dim:
        L = 0.60 * dx

    print("=== Rib parameters ===")
    print(f"rib_thickness={rib_t:.6f}, rib_length={L:.6f}")

    # Build in-context on the selected floor face so that until='next' can terminate on internal roof/web.
    wp = (
        cq.Workplane(obj=solid)
        .add(floor_face)
        .workplane(centerOption="CenterOfBoundBox", invert=invert)
    )

    # Determine which in-plane axis aligns better with global X so rib runs longitudinally.
    xd = wp.plane.xDir
    yd = wp.plane.yDir
    # Choose axis with larger |dot(globalX)| == |component along X|
    x_align = abs(xd.x)
    y_align = abs(yd.x)

    if x_align >= y_align:
        dimx, dimy = L, rib_t
        axis_note = "L along WP x-axis"
    else:
        dimx, dimy = rib_t, L
        axis_note = "L along WP y-axis"

    print(f"Workplane axes alignment: |xd·X|={x_align:.3f}, |yd·X|={y_align:.3f} => {axis_note}")

    # Create the rib as a thin rectangular web and extrude to next face (preferred).
    # Keep it centered in the pocket mid-width by using CenterOfBoundBox origin.
    try:
        result = wp.rect(dimx, dimy, centered=True).extrude(until="next")
        print("Rib extrude used until='next'.")
    except Exception as e1:
        # Fallback: blind extrusion with conservative height towards internal roof (avoid external breakthrough)
        # Use a fraction of overall height.
        h = 0.35 * dy if dy > 0 else 0.35 * max_dim
        if h <= 0:
            h = 10.0 * scale_mm_to_model
        print(f"Rib extrude until='next' failed: {e1}")
        print(f"Falling back to blind extrude height={h:.6f}")
        result = wp.rect(dimx, dimy, centered=True).extrude(h)

    print("=== Done (updated rib placement) ===")
    return result
