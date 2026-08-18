def my_cad_function(args):
    import cadquery as cq
    import os, math

    input_file = os.path.expanduser(args.get("input_file", ""))
    model = cq.importers.importStep(input_file)
    shp = model.val() if hasattr(model, "val") else model

    solids = list(shp.Solids())
    print(f"Loaded STEP: {input_file}")
    print(f"Total solids: {len(solids)}")

    overall_bb = shp.BoundingBox()
    overall_center = overall_bb.center
    print(f"Overall bbox center: ({overall_center.x:.3f}, {overall_center.y:.3f}, {overall_center.z:.3f})")

    def bb_dims(s):
        bb = s.BoundingBox()
        return bb, (bb.xlen, bb.ylen, bb.zlen)

    def unit(v):
        l = math.sqrt(v[0]*v[0] + v[1]*v[1] + v[2]*v[2])
        if l < 1e-12:
            return (1.0, 0.0, 0.0)
        return (v[0]/l, v[1]/l, v[2]/l)

    def dot(a, b):
        return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]

    def cross(a, b):
        return (
            a[1]*b[2] - a[2]*b[1],
            a[2]*b[0] - a[0]*b[2],
            a[0]*b[1] - a[1]*b[0],
        )

    def add(a, b):
        return (a[0] + b[0], a[1] + b[1], a[2] + b[2])

    def mul(a, s):
        return (a[0]*s, a[1]*s, a[2]*s)

    def axis_val(v, axis):
        return {"X": v[0], "Y": v[1], "Z": v[2]}[axis]

    def rounded_rect_sketch(w, h, r):
        rmax = max(0.1, min(w, h) * 0.5 - 0.2)
        rr = max(0.1, min(r, rmax))
        return cq.Sketch().rect(w, h).vertices().fillet(rr)

    # --- pick a slender solid as a seed for cord group ---
    best_i, best_s, best_score = None, None, -1.0
    for i, s in enumerate(solids):
        bb, (dx, dy, dz) = bb_dims(s)
        dims = [dx, dy, dz]
        mx = max(dims)
        mn = max(1e-6, min(dims))
        aspect = mx / mn
        score = aspect
        # prefer long, thin solids
        if mx > 120 and mn < 20:
            score *= 2.0
        if mx < 60:
            score *= 0.2
        if mn > 40:
            score *= 0.05
        if score > best_score:
            best_score = score
            best_i, best_s = i, s

    if best_s is None:
        print("No solids found; returning original")
        return model

    seed_idx = best_i
    seed_bb, (sdx, sdy, sdz) = bb_dims(best_s)
    print(f"Seed cord-like solid index: {seed_idx}")
    print(f"Seed bbox lens: dx={sdx:.3f}, dy={sdy:.3f}, dz={sdz:.3f}")

    # Determine primary axis by seed bbox
    dims = {"X": sdx, "Y": sdy, "Z": sdz}
    axis = max(dims, key=dims.get)
    print(f"Detected cord axis (bbox heuristic): {axis}")

    seed_ctr = (seed_bb.center.x, seed_bb.center.y, seed_bb.center.z)

    if axis == "X":
        a_min, a_max = seed_bb.xmin, seed_bb.xmax
    elif axis == "Y":
        a_min, a_max = seed_bb.ymin, seed_bb.ymax
    else:
        a_min, a_max = seed_bb.zmin, seed_bb.zmax

    a_min -= 80.0
    a_max += 80.0

    cord_group_idx = []
    for i, s in enumerate(solids):
        bb, (dx, dy, dz) = bb_dims(s)
        mx = max(dx, dy, dz)
        mn = min(dx, dy, dz)
        mid = sorted([dx, dy, dz])[1]

        # size gate to avoid capturing housing/cradle
        if mx > 260:
            continue
        if mn > 60:
            continue
        if mid > 160:
            continue

        ctr = (bb.center.x, bb.center.y, bb.center.z)
        a = axis_val(ctr, axis)
        if a < a_min or a > a_max:
            continue

        # proximity in perpendicular space
        if axis == "X":
            dperp = math.hypot(ctr[1]-seed_ctr[1], ctr[2]-seed_ctr[2])
        elif axis == "Y":
            dperp = math.hypot(ctr[0]-seed_ctr[0], ctr[2]-seed_ctr[2])
        else:
            dperp = math.hypot(ctr[0]-seed_ctr[0], ctr[1]-seed_ctr[1])

        if dperp > 220:
            continue

        cord_group_idx.append(i)

    # Always include the seed
    cord_group_idx.append(seed_idx)
    cord_group_idx = sorted(set(cord_group_idx))

    print(f"Cord-group candidate indices: {cord_group_idx}")

    # Build cord compound (avoid fragile boolean fuses at this stage)
    cord_shapes = [solids[i] for i in cord_group_idx]
    cord_comp = cq.Compound.makeCompound(cord_shapes)
    asm_bb = cord_comp.BoundingBox()

    # Determine plug end by farthest extreme from overall center along detected axis
    if axis == "X":
        end_max, end_min, c0 = asm_bb.xmax, asm_bb.xmin, overall_center.x
        plug_end = end_max if abs(end_max - c0) >= abs(end_min - c0) else end_min
        n = (1.0, 0.0, 0.0) if plug_end == end_max else (-1.0, 0.0, 0.0)
        perp_dims = (asm_bb.ylen, asm_bb.zlen)
    elif axis == "Y":
        end_max, end_min, c0 = asm_bb.ymax, asm_bb.ymin, overall_center.y
        plug_end = end_max if abs(end_max - c0) >= abs(end_min - c0) else end_min
        n = (0.0, 1.0, 0.0) if plug_end == end_max else (0.0, -1.0, 0.0)
        perp_dims = (asm_bb.xlen, asm_bb.zlen)
    else:
        end_max, end_min, c0 = asm_bb.zmax, asm_bb.zmin, overall_center.z
        plug_end = end_max if abs(end_max - c0) >= abs(end_min - c0) else end_min
        n = (0.0, 0.0, 1.0) if plug_end == end_max else (0.0, 0.0, -1.0)
        perp_dims = (asm_bb.xlen, asm_bb.ylen)

    # Estimate cord diameter (clamped)
    cord_d = max(3.0, min(12.0, min(perp_dims)))
    print(f"Cord assembly bbox: dx={asm_bb.xlen:.3f}, dy={asm_bb.ylen:.3f}, dz={asm_bb.zlen:.3f}")
    print(f"Plug_end={plug_end:.3f}, n={n}, estimated cord_d={cord_d:.3f}")

    # Build consistent local axes for plug
    up = (0.0, 0.0, 1.0)
    if abs(dot(n, up)) > 0.95:
        up = (0.0, 1.0, 0.0)
    xDir = unit(cross(up, n))

    # --- Europlug parameters (CEE 7/16-like, simplified but realistic) ---
    pin_d = 4.0
    pin_len = 19.0
    pin_spacing = 19.0
    pin_tip_ch = 0.5

    body_w = 35.0
    body_h = 16.0
    body_len = 14.0

    body_side_taper_deg = 1.5
    nose_fillet = 3.0
    body_edge_fillet = 1.2

    recess_d = 6.5
    recess_depth = 1.0

    neck_len = 18.0
    overlap_back = 10.0
    overlap_fwd = 2.0  # ensure geometric overlap with lofted body

    cut_off_len = max(75.0, overlap_back + overlap_fwd + neck_len + body_len + pin_len + 10.0)

    # Cut plane origin = plug_end moved back along -n by cut_off_len
    if axis == "X":
        cut_origin = (plug_end - n[0]*cut_off_len, asm_bb.center.y, asm_bb.center.z)
    elif axis == "Y":
        cut_origin = (asm_bb.center.x, plug_end - n[1]*cut_off_len, asm_bb.center.z)
    else:
        cut_origin = (asm_bb.center.x, asm_bb.center.y, plug_end - n[2]*cut_off_len)

    end_plane = cq.Plane(origin=cq.Vector(*cut_origin), xDir=cq.Vector(*xDir), normal=cq.Vector(*n))
    print(f"Cut plane origin: ({cut_origin[0]:.3f}, {cut_origin[1]:.3f}, {cut_origin[2]:.3f}), cut_off_len={cut_off_len:.2f}")

    # Tool extends from plane in +normal direction (toward plug end)
    cut_tool = cq.Workplane(end_plane).box(2000, 2000, 2000, centered=(True, True, False))

    # Remove existing plug by cutting away the far end
    trimmed_cord_wp = cq.Workplane("XY").newObject([cord_comp]).cut(cut_tool)
    trimmed_cord_shape = trimmed_cord_wp.val()

    # Local planes for new plug
    rear_origin = add(cut_origin, mul(n, neck_len))
    front_origin = add(cut_origin, mul(n, neck_len + body_len))
    rear_plane = cq.Plane(origin=cq.Vector(*rear_origin), xDir=cq.Vector(*xDir), normal=cq.Vector(*n))
    front_plane = cq.Plane(origin=cq.Vector(*front_origin), xDir=cq.Vector(*xDir), normal=cq.Vector(*n))

    # Sleeve overlaps backward into trimmed cord and forward into plug for reliable union
    sleeve_back = cq.Workplane(end_plane).circle((cord_d * 1.06) / 2.0).extrude(-overlap_back)
    sleeve_fwd = cq.Workplane(end_plane).circle((cord_d * 1.06) / 2.0).extrude(overlap_fwd)
    sleeve = sleeve_back.union(sleeve_fwd)

    # Draft-based front size (mild taper to look like real europlug)
    draft = math.tan(math.radians(body_side_taper_deg)) * body_len
    front_w = max(10.0, body_w - 2.0*draft)
    front_h = max(8.0, body_h - 2.0*0.7*draft)

    rear_r = 2.5
    front_r = min(front_w, front_h) * 0.45

    rear_sk = rounded_rect_sketch(body_w, body_h, rear_r)
    front_sk = rounded_rect_sketch(front_w, front_h, front_r)

    # Lofted plug body with strain-relief transition (circle -> rear -> front)
    wp_profiles = cq.Workplane(end_plane).circle((cord_d * 1.10) / 2.0)
    wp_profiles = wp_profiles.add(cq.Workplane(rear_plane).placeSketch(rear_sk))
    wp_profiles = wp_profiles.add(cq.Workplane(front_plane).placeSketch(front_sk))

    plug_body = wp_profiles.loft(combine=True)

    # Fuse sleeve to ensure overlap with the lofted body
    plug_body = plug_body.union(sleeve)

    # Edge treatment for molded look
    try:
        plug_body = plug_body.edges().fillet(body_edge_fillet)
    except Exception as e:
        print(f"WARNING: body edge fillet failed: {e}")

    # Nose rounding on pin-exit face perimeter
    # This selector assumes n is axis-aligned (+/-X,Y,Z) per heuristic.
    if abs(n[0]) > 0.5:
        fwd_sel = ">X" if n[0] > 0 else "<X"
    elif abs(n[1]) > 0.5:
        fwd_sel = ">Y" if n[1] > 0 else "<Y"
    else:
        fwd_sel = ">Z" if n[2] > 0 else "<Z"

    try:
        plug_body = plug_body.faces(fwd_sel).edges().fillet(nose_fillet)
    except Exception as e:
        print(f"WARNING: nose fillet failed: {e}")

    # Pin root recess pockets
    pin_off = pin_spacing / 2.0
    recess_cutter = (
        cq.Workplane(front_plane)
        .pushPoints([(-pin_off, 0.0), (pin_off, 0.0)])
        .circle(recess_d / 2.0)
        .extrude(-recess_depth)
    )
    try:
        plug_body = plug_body.cut(recess_cutter)
    except Exception as e:
        print(f"WARNING: recess cut failed: {e}")

    # Pins
    pins = (
        cq.Workplane(front_plane)
        .pushPoints([(-pin_off, 0.0), (pin_off, 0.0)])
        .circle(pin_d / 2.0)
        .extrude(pin_len)
    )
    try:
        pins = pins.faces(fwd_sel).edges().chamfer(pin_tip_ch)
    except Exception as e:
        print(f"WARNING: pin chamfer failed: {e}")

    plug = plug_body.union(pins)

    # Attempt to fuse plug with trimmed cord; if it fails, keep as compound
    try:
        new_cord_asm_shape = cq.Workplane("XY").newObject([trimmed_cord_shape]).union(plug).val()
    except Exception as e:
        print(f"WARNING: union plug->cord failed, using compound: {e}")
        new_cord_asm_shape = cq.Compound.makeCompound([trimmed_cord_shape, plug.val()])

    # Keep all solids NOT in cord_group_idx
    cord_set = set(cord_group_idx)
    kept_solids = [s for i, s in enumerate(solids) if i not in cord_set]

    out_shapes = kept_solids + [new_cord_asm_shape]
    result = cq.Compound.makeCompound(out_shapes)

    out_bb = result.BoundingBox()
    print(f"Result solids in compound: {len(out_shapes)}")
    print(f"Result bbox: x={out_bb.xlen:.2f}, y={out_bb.ylen:.2f}, z={out_bb.zlen:.2f}")

    return cq.Workplane(obj=result)
