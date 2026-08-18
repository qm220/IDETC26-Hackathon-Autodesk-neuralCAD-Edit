def my_cad_function(args):
    import cadquery as cq
    import os

    # --- Load input STEP ---
    input_file = os.path.expanduser(args.get("input_file", ""))
    shape = cq.importers.importStep(input_file)
    s = shape.val() if hasattr(shape, "val") else shape

    bb = s.BoundingBox()
    xC = 0.5 * (bb.xmin + bb.xmax)
    yMin = bb.ymin
    zMin, zMax = bb.zmin, bb.zmax
    zLen = zMax - zMin

    print("=== Loaded model ===")
    print(f"Valid: {s.isValid()}")
    print(f"BBox xmin/xmax: {bb.xmin:.3f}, {bb.xmax:.3f}")
    print(f"BBox ymin/ymax: {bb.ymin:.3f}, {bb.ymax:.3f}")
    print(f"BBox zmin/zmax: {bb.zmin:.3f}, {bb.zmax:.3f}")
    print(f"BBox center: ({bb.center.x:.3f}, {bb.center.y:.3f}, {bb.center.z:.3f})")
    try:
        print(f"Faces: {len(s.Faces())}, Solids: {len(s.Solids())}")
    except Exception as e:
        print(f"Could not count faces/solids: {e}")

    # --- Parameters from operation.json ---
    track_L = 18.0
    track_W = 8.0
    track_depth = 1.6
    track_r = 2.0

    slider_travel = 6.0
    knob_L = 7.0
    knob_W = 4.0
    knob_H = 1.2

    wall_clear = 0.25

    # Placement: bottom, rear-half, centered left-right
    # Choose a point ~28% of length forward from rear end
    z0 = zMax - 0.28 * zLen

    # --- Create recessed track cut ---
    # Use a cutting tool starting below the lowest point to ensure intersection on curved bottom.
    tool_extra = 2.0  # mm below the lowest bbox Y

    track_plane = cq.Plane(origin=(xC, yMin - tool_extra, z0), xDir=(1, 0, 0), normal=(0, 1, 0))

    track_tool = (
        cq.Workplane(track_plane)
        # NOTE: Workplane axes: X along global X, "Y" in-plane along +/- global Z
        # We want width across X and length along Z => rect(W, L)
        .rect(track_W, track_L)
        .vertices()
        .fillet(track_r)
        .extrude(tool_extra + track_depth)
    )

    modified = shape.cut(track_tool)

    # --- Create slider knob as a separate solid sitting within recess (OFF toward rear) ---
    # Pocket floor is approximately at yMin + track_depth.
    # Knob should extend toward the exterior (downwards) but remain inside recess.
    # So place knob center at y = (yMin + track_depth) - knob_H/2.
    y_knob_center = (yMin + track_depth) - 0.5 * knob_H

    # Place knob near rear end of the track, leaving a bit of clearance.
    # Ensure it stays within track bounds.
    z_knob = z0 + (0.5 * track_L - 0.5 * knob_L - 0.8)

    # Sanity clamp if body is unexpectedly short
    z_knob = max(zMin + 0.2 * zLen, min(z_knob, zMax - 0.2 * zLen))

    knob = (
        cq.Workplane("XY")
        .box(knob_W, knob_H, knob_L)
        .translate((xC, y_knob_center, z_knob))
    )

    # Optional: tiny edge softening on knob (safe if edges exist)
    try:
        knob = knob.edges("|Y").fillet(0.4)
    except Exception as e:
        print(f"Knob fillet skipped: {e}")

    # Return as an assembly to keep the knob as a separate body/component
    assy = cq.Assembly()
    assy.add(modified, name="housing_with_track")
    assy.add(knob, name="bottom_slider_knob")

    print("=== Switch feature added (recess + knob) ===")
    print(f"Track center approx at (x={xC:.3f}, y={yMin:.3f}, z={z0:.3f})")

    return assy
