def my_cad_function(args):
    import cadquery as cq
    import os
    import math

    # --- Load base model ---
    if "input_file" not in args:
        raise ValueError("Expected args['input_file'] for edit operation")
    input_file = os.path.expanduser(args["input_file"])

    base_wp = cq.importers.importStep(input_file)
    base_shape = base_wp.val() if hasattr(base_wp, "val") else base_wp
    if base_shape is None:
        raise ValueError("Failed to import STEP model")

    bbox = base_shape.BoundingBox()
    print("=== Base model bbox ===")
    print(f"xmin/xmax: {bbox.xmin:.3f} / {bbox.xmax:.3f}")
    print(f"ymin/ymax: {bbox.ymin:.3f} / {bbox.ymax:.3f}")
    print(f"zmin/zmax: {bbox.zmin:.3f} / {bbox.zmax:.3f}")
    print(f"xlen/ylen/zlen: {bbox.xlen:.3f} / {bbox.ylen:.3f} / {bbox.zlen:.3f}")

    model = cq.Workplane("XY").add(base_shape)

    # --- Parameters (per plan) ---
    pin_hole_d = 2.5
    pin_r = pin_hole_d / 2.0
    min_edge_dist = 2.0
    chamfer_dist = 0.5

    # --- Helper: robust inside test ---
    def inside(pt, tol=1e-6):
        try:
            return bool(base_shape.isInside(cq.Vector(*pt), tol))
        except Exception:
            # If OCC is picky, slightly relax tolerance
            try:
                return bool(base_shape.isInside(cq.Vector(*pt), 1e-4))
            except Exception:
                return False

    # --- Decide which end is the HOOK end (avoid clevis slot end) ---
    # Clevis end has a slot centered at y=0, so points near that end at y=0 are often OUTSIDE.
    z_samples = [
        bbox.zmin + 0.35 * bbox.zlen,
        bbox.zmin + 0.60 * bbox.zlen,
        bbox.zmin + 0.85 * bbox.zlen,
    ]
    x_left = bbox.xmin + 2.0
    x_right = bbox.xmax - 2.0

    left_inside = sum(1 for z in z_samples if inside((x_left, 0.0, z)))
    right_inside = sum(1 for z in z_samples if inside((x_right, 0.0, z)))

    # Hook end expected to be the end with MORE solid present at y=0
    hook_is_right = True
    if left_inside > right_inside:
        hook_is_right = False
    elif left_inside == right_inside:
        # Tie-break: keep original assumption (+X)
        hook_is_right = True

    hook_end_x = bbox.xmax if hook_is_right else bbox.xmin
    sign = 1.0 if hook_is_right else -1.0

    print("=== End classification (via y=0 solidity sampling) ===")
    print(f"left_end_inside_count={left_inside}  right_end_inside_count={right_inside}")
    print(f"hook_is_right(+X)={hook_is_right}")

    # --- Hole placement (near hook mouth, above seat region) ---
    # Move inward from hook extreme to better intersect the hook throat (avoid being on the very end cap).
    x_inset = 6.0
    hole_x = hook_end_x - sign * x_inset

    # Place high, but keep top edge distance
    hole_z_max = bbox.zmax - (min_edge_dist + pin_r)
    hole_z_min = bbox.zmin + (min_edge_dist + pin_r)
    hole_z = bbox.zmax - (min_edge_dist + pin_r + 0.25)
    hole_z = max(hole_z_min, min(hole_z, hole_z_max))

    # If initial center is not inside, nudge downward until we find material (so we can compute local thickness)
    if not inside((hole_x, 0.0, hole_z)):
        for dz in [0.0, -0.5, -1.0, -1.5, -2.0, -3.0]:
            if inside((hole_x, 0.0, hole_z + dz)):
                hole_z = hole_z + dz
                break

    print("=== Locking pin hole placement ===")
    print(f"hole_d={pin_hole_d:.3f}")
    print(f"hole_center (x,y,z)=({hole_x:.3f}, 0.000, {hole_z:.3f})")

    # --- Determine local half-width at the hole location (so chamfer cutters land on the actual exit faces) ---
    # Binary search for y where we leave the solid at fixed (x,z)
    local_y_half = None
    if inside((hole_x, 0.0, hole_z)):
        ylo, yhi = 0.0, (bbox.ymax - bbox.ymin)  # generous upper bound
        # ensure yhi is outside
        if inside((hole_x, yhi, hole_z)):
            yhi = bbox.ymax + 20.0
        for _ in range(28):
            ym = 0.5 * (ylo + yhi)
            if inside((hole_x, ym, hole_z)):
                ylo = ym
            else:
                yhi = ym
        local_y_half = max(0.5, ylo)
    else:
        # Fallback: use global bbox half-width
        local_y_half = max(0.5, 0.5 * bbox.ylen)

    print(f"local_y_half_width_at_hole ~= {local_y_half:.3f}")

    # --- Operation 1: Through hole along Y (locking pin provision) ---
    cut_len = 2.0 * (local_y_half + 5.0)
    hole_cutter = (
        cq.Workplane("XZ")
        .center(hole_x, hole_z)
        .circle(pin_r)
        .extrude(cut_len / 2.0, both=True)
    )

    result = model.cut(hole_cutter)

    # --- Operation 2: Chamfer/lead-in on both hole entries ---
    # Use local y-exit planes so the lead-in actually intersects the entry edges even if local width is narrow.
    chamf_h = chamfer_dist
    r_big = pin_r + chamfer_dist
    r_small = pin_r

    y_out_pos = local_y_half + 0.05
    y_out_neg = -local_y_half - 0.05

    plane_pos = cq.Plane(origin=(0, y_out_pos, 0), xDir=(1, 0, 0), normal=(0, 1, 0))
    plane_neg = cq.Plane(origin=(0, y_out_neg, 0), xDir=(1, 0, 0), normal=(0, -1, 0))

    chamf_pos = (
        cq.Workplane(plane_pos)
        .center(hole_x, hole_z)
        .circle(r_big)
        .workplane(offset=-chamf_h)
        .circle(r_small)
        .loft(combine=True)
    )

    chamf_neg = (
        cq.Workplane(plane_neg)
        .center(hole_x, hole_z)
        .circle(r_big)
        .workplane(offset=-chamf_h)
        .circle(r_small)
        .loft(combine=True)
    )

    try:
        result = result.cut(chamf_pos)
        result = result.cut(chamf_neg)
        print("Chamfer/lead-in created on both sides via local-thickness conical cuts.")
    except Exception as e:
        print(f"WARNING: Chamfer/lead-in cut failed: {e}")

    return result
