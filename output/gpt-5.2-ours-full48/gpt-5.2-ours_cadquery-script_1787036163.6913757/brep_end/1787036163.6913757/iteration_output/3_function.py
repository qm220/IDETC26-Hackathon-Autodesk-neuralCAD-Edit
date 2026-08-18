def my_cad_function(args):
    import os
    import cadquery as cq

    # ---- Load input STEP ----
    input_file = args.get("input_file", None)
    if not input_file:
        raise ValueError("No input_file provided in args")
    input_file = os.path.expanduser(input_file)

    model = cq.importers.importStep(input_file)
    base_shape = model.val() if hasattr(model, "val") else model

    bbox = base_shape.BoundingBox()
    max_dim = max(bbox.xlen, bbox.ylen, bbox.zlen)

    # Heuristic unit guess (original model looks like ~2x6x1.5 inches)
    if max_dim < 50:
        mm_to_u = 1.0 / 25.4  # mm -> inch
        units_guess = "inch"
    else:
        mm_to_u = 1.0
        units_guess = "mm"

    flange_t = 0.5 * mm_to_u
    flange_w = 2.0 * mm_to_u
    hole_d = 0.5 * mm_to_u
    edge_off = 0.6 * mm_to_u

    print("--- Loaded model ---")
    print(f"BBox (xlen,ylen,zlen)=({bbox.xlen:.6f},{bbox.ylen:.6f},{bbox.zlen:.6f})  guess_units={units_guess}")
    print(f"Using: flange_t={flange_t}, flange_w={flange_w}, hole_d={hole_d}, edge_off={edge_off}")

    # ---- Find bottom rim planar face near global zmin ----
    zmin = bbox.zmin
    tol_z = max(1e-6, 1e-4 * max_dim)

    wp0 = cq.Workplane(obj=base_shape)
    candidate_faces = wp0.faces("<Z").vals()

    bottom_face = None
    best_area = -1.0
    for f in candidate_faces:
        try:
            if f.geomType() != "PLANE":
                continue
            c = f.Center()
            if abs(c.z - zmin) > (5.0 * tol_z):
                continue
            a = f.Area()
            if a > best_area:
                best_area = a
                bottom_face = f
        except Exception:
            continue

    if bottom_face is None:
        raise RuntimeError("Failed to identify bottom reference face")

    wires = list(bottom_face.Wires())
    if len(wires) < 2:
        raise RuntimeError(
            f"Bottom face has {len(wires)} wire(s); expected an inner opening wire for the pocket."
        )

    def bb_area(w):
        bb = w.BoundingBox()
        return bb.xlen * bb.ylen

    wires_sorted = sorted(wires, key=lambda w: bb_area(w))
    inner_wire = wires_sorted[0]
    outer_wire = wires_sorted[-1]
    inner_bb = inner_wire.BoundingBox()
    outer_bb = outer_wire.BoundingBox()

    inner_x, inner_y = inner_bb.xlen, inner_bb.ylen
    inner_cx, inner_cy = inner_bb.center.x, inner_bb.center.y
    outer_x, outer_y = outer_bb.xlen, outer_bb.ylen
    outer_cx, outer_cy = outer_bb.center.x, outer_bb.center.y

    print("--- Bottom face wire inference ---")
    print(f"Outer approx (x,y)=({outer_x:.6f},{outer_y:.6f}) center=({outer_cx:.6f},{outer_cy:.6f})")
    print(f"Inner opening (x,y)=({inner_x:.6f},{inner_y:.6f}) center=({inner_cx:.6f},{inner_cy:.6f})")

    flange_outer_x = outer_x + 2.0 * flange_w
    flange_outer_y = outer_y + 2.0 * flange_w

    # Determine extrude sign so material grows outboard from bottom
    try:
        n = bottom_face.normalAt(0.0, 0.0)
        extrude_dist = flange_t if n.z < 0 else -flange_t
    except Exception:
        extrude_dist = flange_t

    # Workplane on bottom face
    base_wp = cq.Workplane(obj=base_shape).newObject([bottom_face]).workplane(centerOption="CenterOfBoundBox")

    # Inner opening offset relative to outer center
    dx = inner_cx - outer_cx
    dy = inner_cy - outer_cy

    # ---- Robust flange creation (2-step):
    # 1) Extrude a full outer rectangle down
    # 2) Cut the inner opening ONLY through the flange thickness (keeps central pocket open, does not alter the body)
    flange_full = (
        base_wp
        .rect(flange_outer_x, flange_outer_y)
        .extrude(extrude_dist, combine=True)
    )

    # Identify the new flange bottom face (lowest planar face)
    res_shape1 = flange_full.val() if hasattr(flange_full, "val") else flange_full
    bbox1 = res_shape1.BoundingBox()
    zmin1 = bbox1.zmin

    cand = cq.Workplane(obj=res_shape1).faces("<Z").vals()
    flange_bottom_face = None
    best_a = -1.0
    for f in cand:
        try:
            if f.geomType() != "PLANE":
                continue
            c = f.Center()
            if abs(c.z - zmin1) > (10.0 * tol_z + abs(flange_t) * 10.0):
                continue
            a = f.Area()
            if a > best_a:
                best_a = a
                flange_bottom_face = f
        except Exception:
            continue
    if flange_bottom_face is None:
        raise RuntimeError("Failed to identify flange bottom face")

    # Cut inner opening upward by (slightly more than) flange thickness
    # Use invert=True so sketch normal points +Z (into the part)
    cut_depth = abs(flange_t) * 1.05
    wp_flange_bottom = (
        cq.Workplane(obj=res_shape1)
        .newObject([flange_bottom_face])
        .workplane(centerOption="CenterOfBoundBox", invert=True)
    )

    flange_ring = (
        wp_flange_bottom
        .center(dx, dy)
        .rect(inner_x, inner_y)
        .cutBlind(cut_depth)
    )

    # ---- Add 4 mounting holes on the flange bottom face ----
    res_shape2 = flange_ring.val() if hasattr(flange_ring, "val") else flange_ring

    px = flange_outer_x / 2.0 - edge_off
    py = flange_outer_y / 2.0 - edge_off
    hole_pts = [(+px, +py), (+px, -py), (-px, +py), (-px, -py)]

    result = (
        cq.Workplane(obj=res_shape2)
        .newObject([flange_bottom_face])
        .workplane(centerOption="CenterOfBoundBox", invert=True)
        .pushPoints(hole_pts)
        .circle(hole_d / 2.0)
        .cutThruAll()
    )

    print("--- Done operations (updated) ---")
    print(f"Flange outer dims used: ({flange_outer_x:.6f}, {flange_outer_y:.6f})")
    print(f"Inner opening dims used: ({inner_x:.6f}, {inner_y:.6f}) at offset ({dx:.6f}, {dy:.6f})")
    print(f"Hole pts (WP coords): {hole_pts}")

    return result
