def my_cad_function(args):
    import cadquery as cq
    import os

    # --- Load input STEP ---
    input_file = os.path.expanduser(args.get("input_file", ""))
    shape_wp = cq.importers.importStep(input_file)
    top = shape_wp.val() if hasattr(shape_wp, "val") else shape_wp

    bb = top.BoundingBox()
    xC = 0.5 * (bb.xmin + bb.xmax)
    yMin = bb.ymin
    zMin, zMax = bb.zmin, bb.zmax
    zLen = zMax - zMin

    print("=== Loaded model ===")
    print(f"Valid: {top.isValid()}")
    print(f"BBox xmin/xmax: {bb.xmin:.3f}, {bb.xmax:.3f}")
    print(f"BBox ymin/ymax: {bb.ymin:.3f}, {bb.ymax:.3f}")
    print(f"BBox zmin/zmax: {bb.zmin:.3f}, {bb.zmax:.3f}")
    print(f"BBox center: ({bb.center.x:.3f}, {bb.center.y:.3f}, {bb.center.z:.3f})")

    # --- Split solids: assume largest is housing, smaller is wheel ---
    solids = cq.Workplane(obj=top).solids().vals()
    print(f"Solids found: {len(solids)}")
    if len(solids) == 0:
        raise ValueError("No solids found in imported STEP")

    solids_sorted = sorted(solids, key=lambda s: s.Volume(), reverse=True)
    housing = solids_sorted[0]
    other_solids = solids_sorted[1:]
    for i, s in enumerate(solids_sorted):
        try:
            b = s.BoundingBox()
            print(f"  solid[{i}] vol={s.Volume():.3f} bb=({b.xlen:.2f},{b.ylen:.2f},{b.zlen:.2f})")
        except Exception as e:
            print(f"  solid[{i}] info failed: {e}")

    # --- Parameters (from operation.json) ---
    track_L = 18.0
    track_W = 8.0
    track_depth = 1.6
    track_r = 2.0

    knob_L = 7.0
    knob_W = 4.0
    knob_H = 1.2

    # Optional internal cavity (packaging volume) - keep conservative
    cavity_L = 16.0
    cavity_W = 7.0
    cavity_depth = 2.0  # conservative to reduce risk of breaching

    # Placement: bottom, rear-half, centered X
    z0 = zMax - 0.28 * zLen

    # --- Create recessed track cut tool (from below, extrude up) ---
    # Put plane below lowest Y so tool fully intersects even with curvature
    tool_below = 4.0
    tool_extrude = tool_below + track_depth + 2.0

    track_plane = cq.Plane(origin=(xC, yMin - tool_below, z0), xDir=(1, 0, 0), normal=(0, 1, 0))

    track_tool = (
        cq.Workplane(track_plane)
        .rect(track_W, track_L)
        .vertices()
        .fillet(track_r)
        .extrude(tool_extrude)
    )

    housing_wp = cq.Workplane(obj=housing)
    housing_wp = housing_wp.cut(track_tool)

    # --- Optional internal cavity cut (starting at approx pocket floor, into interior +Y) ---
    # If it fails (thin wall / unexpected geometry), skip safely.
    try:
        cavity_plane = cq.Plane(origin=(xC, yMin + track_depth, z0), xDir=(1, 0, 0), normal=(0, 1, 0))
        cavity_tool = (
            cq.Workplane(cavity_plane)
            .rect(cavity_W, cavity_L)
            .vertices()
            .fillet(min(1.5, 0.49 * min(cavity_W, cavity_L)))
            .extrude(cavity_depth)
        )
        housing_wp = housing_wp.cut(cavity_tool)
        cavity_done = True
    except Exception as e:
        cavity_done = False
        print(f"Internal cavity skipped due to error: {e}")

    housing_mod = housing_wp.val()

    # --- Create slider knob as a separate solid inside the recess (OFF toward rear endcap) ---
    # Knob should be visible from underside but not protrude below original envelope.
    # Put knob bottom slightly above yMin.
    knob_bottom_clear = 0.2
    knob_y0 = yMin + knob_bottom_clear

    # Place knob toward rear end within the track
    z_knob = z0 + (0.5 * track_L - 0.5 * knob_L - 1.0)
    # Clamp to keep it reasonably inside the part length if bbox assumptions are off
    z_knob = max(zMin + 0.15 * zLen, min(z_knob, zMax - 0.15 * zLen))

    knob_plane = cq.Plane(origin=(xC, knob_y0, z_knob), xDir=(1, 0, 0), normal=(0, 1, 0))
    knob = (
        cq.Workplane(knob_plane)
        .rect(knob_W, knob_L)
        .vertices()
        .fillet(min(0.9, 0.45 * min(knob_W, knob_L)))
        .extrude(knob_H)
    ).val()

    # --- Build assembly: keep wheel (other solid) unchanged ---
    assy = cq.Assembly()
    assy.add(housing_mod, name="housing_with_bottom_switch_track")
    for i, s in enumerate(other_solids):
        assy.add(s, name=f"original_solid_{i}")
    assy.add(knob, name="bottom_slider_knob")

    print("=== Bottom sliding switch feature created ===")
    print(f"Track center approx: x={xC:.3f}, z={z0:.3f}, yMin={yMin:.3f}")
    print(f"Knob placed approx: x={xC:.3f}, z={z_knob:.3f}, y0={knob_y0:.3f}")
    print(f"Internal cavity created: {cavity_done}")

    return assy
