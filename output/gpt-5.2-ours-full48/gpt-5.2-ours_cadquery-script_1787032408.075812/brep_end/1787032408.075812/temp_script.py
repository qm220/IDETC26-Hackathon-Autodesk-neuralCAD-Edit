def my_cad_function(args):
    import cadquery as cq
    import os

    # --- Load input STEP ---
    input_file = os.path.expanduser(args.get("input_file", ""))
    if not input_file:
        raise ValueError("args['input_file'] not provided")

    shape_wp = cq.importers.importStep(input_file)
    top = shape_wp.val() if hasattr(shape_wp, "val") else shape_wp

    bb = top.BoundingBox()
    xC = 0.5 * (bb.xmin + bb.xmax)
    yMin = bb.ymin
    zMin, zMax = bb.zmin, bb.zmax
    zLen = zMax - zMin

    print("=== Loaded model ===")
    print(f"Input: {input_file}")
    try:
        print(f"Valid: {top.isValid()}")
    except Exception:
        pass
    print(f"BBox xmin/xmax: {bb.xmin:.3f}, {bb.xmax:.3f}")
    print(f"BBox ymin/ymax: {bb.ymin:.3f}, {bb.ymax:.3f}")
    print(f"BBox zmin/zmax: {bb.zmin:.3f}, {bb.zmax:.3f}")
    print(f"BBox center: ({bb.center.x:.3f}, {bb.center.y:.3f}, {bb.center.z:.3f})")

    # --- Split solids: assume largest is housing, smaller is wheel ---
    solids = cq.Workplane(obj=top).solids().vals()
    print(f"Solids found: {len(solids)}")
    if not solids:
        raise ValueError("No solids found in imported STEP")

    solids_sorted = sorted(solids, key=lambda s: s.Volume(), reverse=True)
    housing = solids_sorted[0]
    other_solids = solids_sorted[1:]
    for i, s in enumerate(solids_sorted):
        b = s.BoundingBox()
        print(f"  solid[{i}] vol={s.Volume():.3f} bb=({b.xlen:.2f},{b.ylen:.2f},{b.zlen:.2f})")

    # --- Parameters (from operation.json) ---
    track_L = 18.0
    track_W = 8.0
    track_depth = 1.6
    track_r = 2.0

    slider_travel = 6.0  # not explicitly modeled as motion, but used for placement sanity

    knob_L = 7.0
    knob_W = 4.0
    knob_H = 1.2
    knob_corner_r = 0.8

    slider_clear = 0.25
    edge_break = 0.4

    # Optional internal cavity
    cavity_L = 16.0
    cavity_W = 7.0
    cavity_depth = 2.0  # conservative

    # Placement: bottom, rear-half, centered X
    z0 = zMax - 0.28 * zLen

    # Small epsilon below the bottom so the cut definitely opens to the exterior,
    # while keeping the pocket depth ~ track_depth.
    eps_below = 0.25

    def rounded_rect_sketch(w, l, r):
        # CadQuery 2D fillet must be done via Sketch, not Workplane.fillet()
        r_eff = max(0.0, min(r, 0.49 * min(w, l)))
        sk = cq.Sketch().rect(w, l)
        if r_eff > 1e-6:
            sk = sk.vertices().fillet(r_eff)
        return sk

    # --- Create recessed track cut tool (blind depth) ---
    # Tool runs from slightly below global bottom plane up to yMin + track_depth.
    track_plane = cq.Plane(
        origin=(xC, yMin - eps_below, z0),
        xDir=(1, 0, 0),
        normal=(0, 1, 0),
    )

    track_tool = (
        cq.Workplane(track_plane)
        .placeSketch(rounded_rect_sketch(track_W, track_L, track_r))
        .extrude(track_depth + eps_below)
    )

    housing_wp = cq.Workplane(obj=housing).cut(track_tool)

    # --- Edge break around the track opening (best-effort) ---
    # Select edges near the bottom (y ~ yMin) and near the track XY footprint.
    try:
        x_lim = track_W / 2.0 + 2.0
        z_lim = track_L / 2.0 + 2.0
        y_tol = 0.7

        def edge_near_track_opening(e):
            b = e.BoundingBox()
            cx = 0.5 * (b.xmin + b.xmax)
            cy = 0.5 * (b.ymin + b.ymax)
            cz = 0.5 * (b.zmin + b.zmax)
            if abs(cy - yMin) > y_tol:
                return False
            if abs(cx - xC) > x_lim:
                return False
            if abs(cz - z0) > z_lim:
                return False
            return True

        housing_wp = housing_wp.edges().filter(edge_near_track_opening).fillet(edge_break)
        edgebreak_done = True
    except Exception as e:
        edgebreak_done = False
        print(f"Edge break fillet skipped due to error: {e}")

    # --- Optional internal cavity below the track (best-effort) ---
    cavity_done = False
    try:
        cavity_plane = cq.Plane(
            origin=(xC, yMin + track_depth, z0),
            xDir=(1, 0, 0),
            normal=(0, 1, 0),
        )
        cavity_r = min(1.5, 0.49 * min(cavity_W, cavity_L))
        cavity_tool = (
            cq.Workplane(cavity_plane)
            .placeSketch(rounded_rect_sketch(cavity_W, cavity_L, cavity_r))
            .extrude(cavity_depth)
        )
        housing_wp = housing_wp.cut(cavity_tool)
        cavity_done = True
    except Exception as e:
        print(f"Internal cavity skipped due to error: {e}")

    housing_mod = housing_wp.val()

    # --- Create slider knob as a separate solid (inside recess, OFF toward rear) ---
    # Place knob within track bounds, toward rear end.
    z_knob = z0 + (0.5 * track_L - 0.5 * knob_L - 1.0)
    # Clamp within part length
    z_knob = max(zMin + 0.15 * zLen, min(z_knob, zMax - 0.15 * zLen))

    # Ensure knob does not protrude below original envelope: y >= yMin.
    knob_bottom_clear = 0.2
    knob_H_eff = min(knob_H, max(0.0, track_depth - knob_bottom_clear))
    if knob_H_eff <= 1e-6:
        print("Knob height collapsed by constraints; skipping knob creation.")
        knob_val = None
    else:
        knob_plane = cq.Plane(
            origin=(xC, yMin + track_depth, z_knob),
            xDir=(1, 0, 0),
            normal=(0, 1, 0),
        )
        # footprint sized to ensure clearance; user provided knob is already small vs track
        if (knob_W + 2 * slider_clear) > track_W or (knob_L + 2 * slider_clear) > track_L:
            print("WARNING: knob+clearance exceeds track. Consider reducing knob or increasing track.")

        knob_wp = (
            cq.Workplane(knob_plane)
            .placeSketch(rounded_rect_sketch(knob_W, knob_L, min(knob_corner_r, 0.49 * min(knob_W, knob_L))))
            # extrude DOWN toward exterior opening, but keep above yMin
            .extrude(-knob_H_eff)
        )
        # Comfort fillet (best-effort)
        try:
            knob_wp = knob_wp.edges("|Y").fillet(0.35)
        except Exception as e:
            print(f"Knob fillet skipped due to error: {e}")
        knob_val = knob_wp.val()

    # --- Build assembly: keep wheel (other solid) unchanged ---
    assy = cq.Assembly()
    assy.add(housing_mod, name="housing_with_bottom_switch")
    for i, s in enumerate(other_solids):
        assy.add(s, name=f"original_solid_{i}")
    if knob_val is not None:
        assy.add(knob_val, name="bottom_slider_knob")

    print("=== Bottom sliding switch feature created ===")
    print(f"Track center approx: x={xC:.3f}, z={z0:.3f}, yMin={yMin:.3f}")
    print(f"Track dims LxWxd: {track_L} x {track_W} x {track_depth}")
    print(f"Knob dims LxWxd: {knob_L} x {knob_W} x {knob_H_eff:.3f}")
    print(f"Knob center approx: x={xC:.3f}, z={z_knob:.3f}")
    print(f"Edge break applied: {edgebreak_done}")
    print(f"Internal cavity created: {cavity_done}")

    return assy
