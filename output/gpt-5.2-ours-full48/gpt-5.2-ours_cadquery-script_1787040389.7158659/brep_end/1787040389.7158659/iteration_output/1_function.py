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

    # Wrap the imported shape into a Workplane for boolean ops
    model = cq.Workplane("XY").add(base_shape)

    # --- Identify hook seat-like cylinder (r ~ 3) near +X ---
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

    cyl_rows = [row for row in cyl_rows if row[0] is not None]
    cyl_rows_sorted = sorted(cyl_rows, key=lambda t: (t[1], t[3]))
    print("=== Cylindrical faces (radius, cx, cy, cz, xlen, ylen, zlen) [sorted by cx,cz] ===")
    for row in cyl_rows_sorted[:40]:
        print("  ", " ".join(f"{v:.3f}" for v in row))
    if len(cyl_rows_sorted) > 40:
        print(f"  ... ({len(cyl_rows_sorted)-40} more)")

    hook_x_threshold = bbox.xmax - 0.30 * bbox.xlen
    seat_candidates = [(r, cx, cz) for (r, cx, cy, cz, xl, yl, zl) in cyl_rows_sorted
                       if (cx >= hook_x_threshold and abs(r - 3.0) <= 0.65)]

    if seat_candidates:
        # choose the lower-Z one to represent the concave seat (distinct from a top patch)
        seat_r, seat_cx, seat_cz = sorted(seat_candidates, key=lambda t: t[2])[0]
        print(f"Selected seat-like cylinder: r={seat_r:.3f}, cx={seat_cx:.3f}, cz={seat_cz:.3f}")
    else:
        # fallback (still functional: place pin hole near top)
        seat_r, seat_cx, seat_cz = (3.0, bbox.xmax - 10.0, 0.40 * bbox.zmax)
        print("WARNING: No r~3 cylinder found near hook end; using fallback seat reference")

    # --- Parameters from plan ---
    pin_hole_d = 2.5
    pin_r = pin_hole_d / 2.0
    min_edge_dist = 2.0
    min_above_seat = 1.5
    chamfer_dist = 0.5

    # --- Decide hole center (X,Z) ---
    # Put the pin close to the mouth (near +X extreme) while leaving outer wall ligament.
    hole_x = bbox.xmax - (min_edge_dist + pin_r + 0.75)

    # Ensure hole is above the seat: hole bottom edge >= (seat center z + seat r + clearance)
    hole_z_min = seat_cz + seat_r + min_above_seat + pin_r

    # Keep below the top by edge distance
    hole_z_max = bbox.zmax - (min_edge_dist + pin_r)

    # Keep above bottom by edge distance
    hole_z_floor = bbox.zmin + (min_edge_dist + pin_r)

    hole_z = hole_z_min
    if hole_z > hole_z_max:
        print("WARNING: Not enough vertical room to satisfy above-seat + top edge distance. Clamping Z to top limit.")
        hole_z = hole_z_max
        # If clamped, also move slightly inward in X to preserve strength (best effort)
        hole_x = min(hole_x, bbox.xmax - 6.0)

    hole_z = max(hole_z_floor, min(hole_z, hole_z_max))

    # Symmetric mid-plane through thickness
    hole_y = 0.0

    print("=== Locking pin hole placement ===")
    print(f"hole_d={pin_hole_d:.3f}")
    print(f"hole_center (x,y,z)=({hole_x:.3f}, {hole_y:.3f}, {hole_z:.3f})")

    # --- Cut through-hole along Y (normal to XZ plane) ---
    cut_len = bbox.ylen + 50.0
    cutter = (
        cq.Workplane("XZ")
        .center(hole_x, hole_z)
        .circle(pin_r)
        .extrude(cut_len / 2.0, both=True)
    )

    result = model.cut(cutter)

    # --- Chamfer both entries of the new hole (deburr/lead-in) ---
    def is_target_hole_edge(e):
        try:
            if e.geomType() != "CIRCLE":
                return False
            if abs(float(e.radius()) - pin_r) > 0.20:
                return False
            c = e.Center()
            # Centers should be at same XZ as hole (Y differs by face)
            if abs(c.x - hole_x) > 1.0:
                return False
            if abs(c.z - hole_z) > 1.0:
                return False
            return True
        except Exception:
            return False

    chamfer_applied = False
    try:
        # Prefer chamfering only the two circular edges at the two outer faces
        sel = result.edges().filter(is_target_hole_edge)
        # If selection is empty, this will throw when chamfering; catch below
        result = sel.chamfer(chamfer_dist)
        chamfer_applied = True
        print("Chamfer applied to target hole entry edges via edge filter.")
    except Exception as e:
        print(f"WARNING: Filter-based chamfer failed: {e}")

    if not chamfer_applied:
        # Fallback: nearest edge to points near +/-Y extremes at hole XZ
        pt_pos = cq.Vector(hole_x, bbox.ymax + 1.0, hole_z)
        pt_neg = cq.Vector(hole_x, bbox.ymin - 1.0, hole_z)
        try:
            result = result.edges(cq.selectors.NearestToPointSelector(pt_pos)).chamfer(chamfer_dist)
            print("Chamfer applied at +Y entry via nearest-point selector.")
        except Exception as e:
            print(f"WARNING: Failed to chamfer +Y entry: {e}")
        try:
            result = result.edges(cq.selectors.NearestToPointSelector(pt_neg)).chamfer(chamfer_dist)
            print("Chamfer applied at -Y entry via nearest-point selector.")
        except Exception as e:
            print(f"WARNING: Failed to chamfer -Y entry: {e}")

    return result
