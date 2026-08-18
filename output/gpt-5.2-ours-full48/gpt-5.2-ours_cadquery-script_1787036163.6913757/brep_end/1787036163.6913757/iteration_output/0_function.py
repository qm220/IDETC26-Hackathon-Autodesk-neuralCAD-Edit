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

    # Heuristic: if the part is ~2x6x1.5 (inches) then max_dim ~6.
    # If it is in mm, max_dim would be ~152.
    if max_dim < 50:
        mm_to_u = 1.0 / 25.4  # convert mm -> inches
        units_guess = "inch"
    else:
        mm_to_u = 1.0  # already mm
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
    candidate_faces = wp0.faces("<Z").vals()  # faces whose normals point -Z

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
        # Fallback: choose planar face among all faces closest to zmin
        print("WARNING: Could not find bottom face via <Z planar filter; trying all planar faces")
        bottom_face = None
        best = None
        for f in base_shape.Faces():
            if f.geomType() != "PLANE":
                continue
            c = f.Center()
            dz = abs(c.z - zmin)
            a = f.Area()
            key = (dz, -a)
            if best is None or key < best:
                best = key
                bottom_face = f

    if bottom_face is None:
        raise RuntimeError("Failed to identify bottom reference face")

    # Determine inner opening from bottom face wires (expect: outer wire + inner wire)
    wires = bottom_face.Wires()
    if len(wires) < 2:
        print(f"WARNING: bottom face has {len(wires)} wire(s); expected inner opening. Will approximate inner opening from smallest face on <Z")

    # Pick smallest-bbox wire as inner (opening), largest as outer
    def bb_area(w):
        bb = w.BoundingBox()
        return bb.xlen * bb.ylen

    inner_wire = None
    if len(wires) >= 2:
        wires_sorted = sorted(list(wires), key=lambda w: bb_area(w))
        inner_wire = wires_sorted[0]
        outer_wire = wires_sorted[-1]
        inner_bb = inner_wire.BoundingBox()
        outer_bb = outer_wire.BoundingBox()
        inner_x, inner_y = inner_bb.xlen, inner_bb.ylen
        inner_cx, inner_cy = inner_bb.center.x, inner_bb.center.y
        outer_x, outer_y = outer_bb.xlen, outer_bb.ylen
        outer_cx, outer_cy = outer_bb.center.x, outer_bb.center.y
    else:
        # Use global bbox for outer, and make a conservative inner opening estimate
        outer_x, outer_y = bbox.xlen, bbox.ylen
        outer_cx, outer_cy = bbox.center.x, bbox.center.y
        inner_x, inner_y = 0.6 * outer_x, 0.9 * outer_y
        inner_cx, inner_cy = outer_cx, outer_cy

    print("--- Bottom face wire inference ---")
    print(f"Outer approx (x,y)=({outer_x:.6f},{outer_y:.6f}) center=({outer_cx:.6f},{outer_cy:.6f})")
    print(f"Inner opening (x,y)=({inner_x:.6f},{inner_y:.6f}) center=({inner_cx:.6f},{inner_cy:.6f})")

    # ---- Create flange: rectangular ring, starting on bottom rim face, extrude outward (down) ----
    # outer flange dims = existing outer footprint + 2*flange_w
    flange_outer_x = outer_x + 2.0 * flange_w
    flange_outer_y = outer_y + 2.0 * flange_w

    # Use the bottom face normal to pick extrude sign (extrude goes along WP normal)
    try:
        n = bottom_face.normalAt(0.0, 0.0)
        extrude_dist = flange_t if n.z < 0 else -flange_t
    except Exception:
        # assume bottom face points -Z
        extrude_dist = flange_t

    base_wp = cq.Workplane(obj=base_shape).newObject([bottom_face]).workplane()

    # Make ring profile centered on inferred outer center; inner centered on inferred inner center.
    # If they differ slightly, place inner relative to outer by translating before making second rect.
    dx = inner_cx - outer_cx
    dy = inner_cy - outer_cy

    flange_profile = (
        base_wp
        .center(outer_cx, outer_cy)
        .rect(flange_outer_x, flange_outer_y)
        .center(dx, dy)
        .rect(inner_x, inner_y)
        .reset()
    )

    res = flange_profile.extrude(extrude_dist, combine=True)

    # ---- Add 4 mounting holes on the new flange bottom face ----
    res_shape = res.val() if hasattr(res, "val") else res
    bbox2 = res_shape.BoundingBox()

    # Find bottom-most planar face (flange bottom)
    zmin2 = bbox2.zmin
    cand2 = cq.Workplane(obj=res_shape).faces("<Z").vals()
    flange_bottom_face = None
    best_area2 = -1.0
    for f in cand2:
        try:
            if f.geomType() != "PLANE":
                continue
            c = f.Center()
            if abs(c.z - zmin2) > (5.0 * tol_z + abs(flange_t) * 2.0):
                continue
            a = f.Area()
            if a > best_area2:
                best_area2 = a
                flange_bottom_face = f
        except Exception:
            continue

    if flange_bottom_face is None:
        raise RuntimeError("Failed to identify flange bottom face")

    hx = flange_outer_x / 2.0
    hy = flange_outer_y / 2.0

    # Hole centers: 0.6mm inboard from both adjacent outer edges of flange
    px = hx - edge_off
    py = hy - edge_off
    hole_pts = [(+px, +py), (+px, -py), (-px, +py), (-px, -py)]

    # Workplane on flange bottom face; invert so +normal points into the part (upwards)
    hole_wp = cq.Workplane(obj=res_shape).newObject([flange_bottom_face]).workplane(invert=True)

    res2 = (
        hole_wp
        .pushPoints(hole_pts)
        .circle(hole_d / 2.0)
        .cutThruAll()
    )

    print("--- Done operations ---")
    print(f"Flange outer dims used: ({flange_outer_x:.6f}, {flange_outer_y:.6f})")
    print(f"Hole pts (local WP coords): {hole_pts}")

    return res2
