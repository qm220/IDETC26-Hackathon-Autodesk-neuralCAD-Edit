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

    # --- Try to identify a seat-like cylinder (r ~ 3) near +X to place pin above it ---
    cyl_rows = []
    for f in base_shape.Faces():
        try:
            if f.geomType() != "CYLINDER":
                continue
            r = float(f.radius())
            c = f.Center()
            bb = f.BoundingBox()
            cyl_rows.append((r, c.x, c.y, c.z, bb.xlen, bb.ylen, bb.zlen))
        except Exception:
            continue

    cyl_rows_sorted = sorted(cyl_rows, key=lambda t: (t[1], t[3]))
    print("=== Cylindrical faces (radius, cx, cy, cz, xlen, ylen, zlen) [sorted by cx,cz] ===")
    for row in cyl_rows_sorted[:60]:
        print("  ", " ".join(f"{v:.3f}" for v in row))
    if len(cyl_rows_sorted) > 60:
        print(f"  ... ({len(cyl_rows_sorted)-60} more)")

    hook_x_threshold = bbox.xmax - 0.30 * bbox.xlen
    seat_candidates = [(r, cx, cz) for (r, cx, cy, cz, xl, yl, zl) in cyl_rows_sorted
                       if (cx >= hook_x_threshold and abs(r - 3.0) <= 0.75)]

    if seat_candidates:
        seat_r, seat_cx, seat_cz = sorted(seat_candidates, key=lambda t: t[2])[0]
        print(f"Selected seat-like cylinder: r={seat_r:.3f}, cx={seat_cx:.3f}, cz={seat_cz:.3f}")
    else:
        seat_r, seat_cx, seat_cz = (3.0, bbox.xmax - 10.0, 0.40 * bbox.zmax)
        print("WARNING: No r~3 cylinder found near hook end; using fallback seat reference")

    # --- Parameters per plan ---
    pin_hole_d = 2.5
    pin_r = pin_hole_d / 2.0
    min_edge_dist = 2.0
    min_above_seat = 1.5
    chamfer_dist = 0.5  # requested

    # --- Decide hole center (X,Z) in global coordinates ---
    # Place near +X end while keeping a ligament to the outer boundary.
    hole_x = bbox.xmax - (min_edge_dist + pin_r + 0.75)

    # Ensure hole is above the seat's top + clearance
    hole_z_min = seat_cz + seat_r + min_above_seat + pin_r
    hole_z_max = bbox.zmax - (min_edge_dist + pin_r)
    hole_z_floor = bbox.zmin + (min_edge_dist + pin_r)

    hole_z = hole_z_min
    if hole_z > hole_z_max:
        print("WARNING: Not enough vertical room to satisfy above-seat + top edge distance. Clamping Z to top limit.")
        hole_z = hole_z_max
        hole_x = min(hole_x, bbox.xmax - 6.0)

    hole_z = max(hole_z_floor, min(hole_z, hole_z_max))

    hole_y = 0.0

    print("=== Locking pin hole placement ===")
    print(f"hole_d={pin_hole_d:.3f}")
    print(f"hole_center (x,y,z)=({hole_x:.3f}, {hole_y:.3f}, {hole_z:.3f})")

    # --- Operation 1: Create through-hole along Y (locking pin provision) ---
    cut_len = bbox.ylen + 60.0
    hole_cutter = (
        cq.Workplane("XZ")
        .center(hole_x, hole_z)
        .circle(pin_r)
        .extrude(cut_len / 2.0, both=True)
    )

    result = model.cut(hole_cutter)

    # --- Operation 2: Add chamfer/lead-in at both hole entries ---
    # The hole exits may not form perfectly circular edges (depending on outer surfaces),
    # so instead of relying on Edge.chamfer() selection, we cut two shallow conical lead-ins
    # (equivalent functional chamfer/deburr) from both +Y and -Y sides.

    chamf_h = chamfer_dist  # 45°-ish lead-in depth
    r_big = pin_r + chamfer_dist
    r_small = pin_r

    # +Y side countersink-like cutter (start just outside bbox.ymax and go inward)
    y_out_pos = bbox.ymax + 0.05
    plane_pos = cq.Plane(origin=(0, y_out_pos, 0), xDir=(1, 0, 0), normal=(0, 1, 0))
    chamf_pos = (cq.Workplane(plane_pos)
                 .center(hole_x, hole_z)
                 .circle(r_big)
                 .workplane(offset=-chamf_h)
                 .circle(r_small)
                 .loft(combine=True))

    # -Y side cutter
    y_out_neg = bbox.ymin - 0.05
    plane_neg = cq.Plane(origin=(0, y_out_neg, 0), xDir=(1, 0, 0), normal=(0, 1, 0))
    chamf_neg = (cq.Workplane(plane_neg)
                 .center(hole_x, hole_z)
                 .circle(r_big)
                 .workplane(offset=+chamf_h)
                 .circle(r_small)
                 .loft(combine=True))

    try:
        result = result.cut(chamf_pos)
        result = result.cut(chamf_neg)
        print("Chamfer/lead-in created on both sides via conical cut (robust, independent of edge type).")
    except Exception as e:
        print(f"WARNING: Chamfer/lead-in conical cut failed: {e}")

    return result
