def my_cad_function(args):
    import cadquery as cq
    import os

    # --- Load base model ---
    if "input_file" not in args:
        raise ValueError("Expected args['input_file'] for edit operation")
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)

    solid = model.val() if hasattr(model, "val") else model
    if solid is None:
        raise ValueError("Failed to import STEP model")

    bbox = solid.BoundingBox()
    print("=== Base model bbox ===")
    print(f"xmin/xmax: {bbox.xmin:.3f} / {bbox.xmax:.3f}")
    print(f"ymin/ymax: {bbox.ymin:.3f} / {bbox.ymax:.3f}")
    print(f"zmin/zmax: {bbox.zmin:.3f} / {bbox.zmax:.3f}")
    print(f"xlen/ylen/zlen: {bbox.xlen:.3f} / {bbox.ylen:.3f} / {bbox.zlen:.3f}")

    # --- Inspect cylindrical faces to locate hook seat cylinder (r~3 near +X) ---
    cyl_info = []
    for f in solid.Faces():
        ff = cq.Face(f)
        gt = None
        try:
            gt = ff.geomType()
        except Exception:
            gt = None
        if gt != "CYLINDER":
            continue
        try:
            r = float(ff.radius())
        except Exception:
            r = None
        c = ff.Center()
        bb = ff.BoundingBox()
        cyl_info.append((r, c.x, c.y, c.z, bb.xlen, bb.ylen, bb.zlen))

    cyl_info_sorted = sorted([ci for ci in cyl_info if ci[0] is not None], key=lambda t: (t[1], t[3]))
    print("=== Cylindrical faces (radius, cx, cy, cz, xlen, ylen, zlen) [sorted by cx,cz] ===")
    for ci in cyl_info_sorted[:30]:
        print("  ", " ".join(f"{v:.3f}" for v in ci))
    if len(cyl_info_sorted) > 30:
        print(f"  ... ({len(cyl_info_sorted)-30} more)")

    # Hook end is at +X
    hook_x_threshold = bbox.xmax - 0.35 * bbox.xlen

    # Candidate seat/notch cylinder: radius ~3, near +X; pick the lower-Z one (seat is below top pad)
    seat_candidate = None
    for r, cx, cy, cz, xl, yl, zl in cyl_info_sorted:
        if cx < hook_x_threshold:
            continue
        if abs(r - 3.0) > 0.65:
            continue
        # Avoid selecting the clevis pin holes at -X via cx threshold; also prefer cylinders that span across Y
        seat_candidate = (r, cx, cz)
        # We'll collect all and pick lowest cz below.

    seat_candidates = [(r, cx, cz) for (r, cx, cy, cz, xl, yl, zl) in cyl_info_sorted
                       if (cx >= hook_x_threshold and r is not None and abs(r - 3.0) <= 0.65)]

    if seat_candidates:
        seat_r, seat_cx, seat_cz = sorted(seat_candidates, key=lambda t: t[2])[0]
        print(f"Selected seat-like cylinder: r={seat_r:.3f}, cx={seat_cx:.3f}, cz={seat_cz:.3f}")
    else:
        seat_r, seat_cx, seat_cz = (3.0, bbox.xmax - 10.0, (bbox.zmin + bbox.zmax) * 0.5)
        print("WARNING: No r~3 cylinder found near hook end; using fallback seat reference")

    # --- Parameters from plan ---
    pin_hole_d = 2.5
    pin_r = pin_hole_d / 2.0
    min_edge_dist = 2.0
    min_above_seat = 1.5
    chamfer_dist = 0.5

    # --- Decide hole center (X,Z) ---
    # Place hole near the mouth (close to xmax) while keeping edge distance.
    hole_x = bbox.xmax - (min_edge_dist + pin_r + 0.75)  # small extra margin

    # Ensure hole is above the seat: keep hole's lower edge above (seat_cz + seat_r + min_above_seat)
    hole_z_min = seat_cz + seat_r + min_above_seat + pin_r
    # Also keep it below the top surface by edge distance
    hole_z_max = bbox.zmax - (min_edge_dist + pin_r)
    hole_z = max(hole_z_min, min(hole_z_max, hole_z_min))  # start at min requirement
    # If that violates top clearance, clamp down.
    hole_z = min(hole_z, hole_z_max)
    # If we had to clamp down below required, move slightly inward in X to gain material (best-effort)
    if hole_z < hole_z_min:
        print("WARNING: Top clearance limits hole above-seat requirement; clamping Z and moving X inward")
        hole_z = hole_z_max
        hole_x = min(hole_x, bbox.xmax - 6.0)

    # Keep hole within body Z bounds with some safety
    hole_z = max(bbox.zmin + (min_edge_dist + pin_r), min(hole_z, bbox.zmax - (min_edge_dist + pin_r)))

    # Place at mid-thickness in Y (symmetry plane)
    hole_y = 0.0

    print("=== Locking pin hole placement ===")
    print(f"hole_d={pin_hole_d:.3f}")
    print(f"hole_center (x,y,z)=({hole_x:.3f}, {hole_y:.3f}, {hole_z:.3f})")

    # --- Create cutter: cylinder along Y, centered at y=0, extrude long enough to cut through ---
    cut_len = bbox.ylen + 50.0
    cutter = (
        cq.Workplane("XZ")
        .center(hole_x, hole_z)
        .circle(pin_hole_d / 2.0)
        .extrude(cut_len / 2.0, both=True)
    )

    result = model.cut(cutter)

    # --- Chamfer both hole entries (best-effort via nearest edge selection) ---
    # Use points near +/-Y extremes at the hole location.
    pt_pos = cq.Vector(hole_x, bbox.ymax + 1.0, hole_z)
    pt_neg = cq.Vector(hole_x, bbox.ymin - 1.0, hole_z)

    try:
        # Chamfer +Y entry
        result = result.edges(cq.selectors.NearestToPointSelector(pt_pos)).chamfer(chamfer_dist)
    except Exception as e:
        print(f"WARNING: Failed to chamfer +Y hole edge: {e}")

    try:
        # Chamfer -Y entry
        result = result.edges(cq.selectors.NearestToPointSelector(pt_neg)).chamfer(chamfer_dist)
    except Exception as e:
        print(f"WARNING: Failed to chamfer -Y hole edge: {e}")

    return result
