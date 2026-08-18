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
        if l < 1e-9:
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

    def sub(a, b):
        return (a[0] - b[0], a[1] - b[1], a[2] - b[2])

    def mul(a, s):
        return (a[0]*s, a[1]*s, a[2]*s)

    def rounded_rect_face(wp, w, h, r):
        # returns Workplane containing a face wire
        w = float(w); h = float(h); r = float(r)
        rmax = max(0.0, min(w, h) * 0.5 - 0.2)
        r = max(0.0, min(r, rmax))
        return wp.sketch().rect(w, h).vertices().fillet(r).finalize()

    # --- Identify cord(+plug) solid by slenderness ---
    best_i, best_s, best_score = None, None, -1.0
    for i, s in enumerate(solids):
        bb, (dx, dy, dz) = bb_dims(s)
        dims = [dx, dy, dz]
        mx = max(dims)
        mn = max(1e-6, min(dims))
        aspect = mx / mn
        score = aspect
        # prefer long slender parts
        if mx < 80:
            score *= 0.25
        if mn > 35:
            score *= 0.10
        if mx > 120 and mn < 20:
            score *= 2.0
        if score > best_score:
            best_score = score
            best_i, best_s = i, s

    if best_s is None:
        print("No solids found; returning original model")
        return model

    cord_idx, cord_solid = best_i, best_s
    cord_bb, (cdx, cdy, cdz) = bb_dims(cord_solid)
    print(f"Selected cord-like solid index: {cord_idx}")
    print(f"Cord-like bbox lens: dx={cdx:.3f}, dy={cdy:.3f}, dz={cdz:.3f}")

    # Determine cord axis and outward (plug) direction (axis-aligned heuristic)
    dims = {"X": cdx, "Y": cdy, "Z": cdz}
    axis = max(dims, key=dims.get)

    if axis == "X":
        end_max, end_min, c0 = cord_bb.xmax, cord_bb.xmin, overall_center.x
        plug_end = end_max if abs(end_max - c0) >= abs(end_min - c0) else end_min
        n = (1.0, 0.0, 0.0) if plug_end == end_max else (-1.0, 0.0, 0.0)
        perp_dims = (cdy, cdz)
    elif axis == "Y":
        end_max, end_min, c0 = cord_bb.ymax, cord_bb.ymin, overall_center.y
        plug_end = end_max if abs(end_max - c0) >= abs(end_min - c0) else end_min
        n = (0.0, 1.0, 0.0) if plug_end == end_max else (0.0, -1.0, 0.0)
        perp_dims = (cdx, cdz)
    else:
        end_max, end_min, c0 = cord_bb.zmax, cord_bb.zmin, overall_center.z
        plug_end = end_max if abs(end_max - c0) >= abs(end_min - c0) else end_min
        n = (0.0, 0.0, 1.0) if plug_end == end_max else (0.0, 0.0, -1.0)
        perp_dims = (cdx, cdy)

    cord_d = max(3.0, min(10.0, min(perp_dims)))
    print(f"Detected cord axis: {axis}, plug_end={plug_end:.3f}, normal n={n}, estimated cord_d={cord_d:.3f}")

    # --- Europlug parameters (mm) ---
    pin_d = 4.0
    pin_len = 19.0
    pin_spacing = 19.0
    pin_tip_ch = 0.5

    body_w = 35.0
    body_h = 16.0
    body_t = 14.0
    body_edge_fillet = 2.0

    recess_d = 6.5
    recess_depth = 1.0
    side_taper_deg = 1.5
    nose_fillet = 3.0

    # strain relief
    overlap_into_cord = 2.0
    neck_len = 18.0
    neck_taper_deg = 6.0

    plug_total_len = overlap_into_cord + neck_len + body_t + pin_len
    cut_off_len = plug_total_len + 10.0

    # --- Build a cut plane to remove old plug geometry from the cord solid ---
    if axis == "X":
        cut_coord = plug_end - n[0] * cut_off_len
        cut_origin = (cut_coord, cord_bb.center.y, cord_bb.center.z)
    elif axis == "Y":
        cut_coord = plug_end - n[1] * cut_off_len
        cut_origin = (cord_bb.center.x, cut_coord, cord_bb.center.z)
    else:
        cut_coord = plug_end - n[2] * cut_off_len
        cut_origin = (cord_bb.center.x, cord_bb.center.y, cut_coord)

    up = (0.0, 0.0, 1.0)
    if abs(dot(n, up)) > 0.95:
        up = (0.0, 1.0, 0.0)
    xDir = unit(cross(up, n))

    cut_plane = cq.Plane(origin=cq.Vector(*cut_origin), xDir=cq.Vector(*xDir), normal=cq.Vector(*n))
    print(f"Cut plane origin: ({cut_origin[0]:.3f}, {cut_origin[1]:.3f}, {cut_origin[2]:.3f}), cut_off_len={cut_off_len:.2f}")

    # Tool extends from plane in +normal direction (local +Z), removing plug-end portion
    cut_tool = cq.Workplane(cut_plane).box(2000, 2000, 2000, centered=(True, True, False))
    trimmed_cord_shape = cq.Workplane(obj=cord_solid).cut(cut_tool).val()

    # Remove separate old plug solids (heuristic)
    kept_solids = []
    removed = []
    for i, s in enumerate(solids):
        if i == cord_idx:
            continue
        bb, (dx, dy, dz) = bb_dims(s)
        mx = max(dx, dy, dz)
        ctr = (bb.center.x, bb.center.y, bb.center.z)
        proj = dot(sub(ctr, cut_origin), n)
        # beyond cut plane and not huge (avoid deleting housing)
        if proj > 5.0 and mx < 300.0:
            removed.append(i)
        else:
            kept_solids.append(s)
    print(f"Removed candidate plug solids indices (heuristic): {removed}")

    # --- Build new Europlug aligned to cord end ---
    # Planes along plug axis
    base_origin = add(cut_origin, mul(n, -overlap_into_cord))
    rear_origin = add(base_origin, mul(n, neck_len))
    front_origin = add(rear_origin, mul(n, body_t))

    base_plane = cq.Plane(origin=cq.Vector(*base_origin), xDir=cq.Vector(*xDir), normal=cq.Vector(*n))
    rear_plane = cq.Plane(origin=cq.Vector(*rear_origin), xDir=cq.Vector(*xDir), normal=cq.Vector(*n))
    front_plane = cq.Plane(origin=cq.Vector(*front_origin), xDir=cq.Vector(*xDir), normal=cq.Vector(*n))

    # Determine forward face selector for chamfers/fillets (n is axis-aligned)
    nx, ny, nz = n
    if abs(nx) > 0.5:
        fwd_sel = ">X" if nx > 0 else "<X"
    elif abs(ny) > 0.5:
        fwd_sel = ">Y" if ny > 0 else "<Y"
    else:
        fwd_sel = ">Z" if nz > 0 else "<Z"
    print(f"Forward face selector: {fwd_sel} (n={n})")

    # Strain relief neck (tapered)
    neck = (
        cq.Workplane(base_plane)
        .circle(cord_d / 2.0)
        .extrude(neck_len, taper=neck_taper_deg)
    )

    # Plug body (drafted rounded rectangle)
    body = (
        rounded_rect_face(cq.Workplane(rear_plane), body_w, body_h, body_edge_fillet)
        .extrude(body_t, taper=-side_taper_deg)
    )

    # Fillet body edges (best effort)
    try:
        body = body.edges().fillet(body_edge_fillet)
    except Exception as e:
        print(f"WARNING: body global fillet({body_edge_fillet}) failed: {e}")
        try:
            body = body.edges().fillet(max(0.8, body_edge_fillet * 0.5))
        except Exception as e2:
            print(f"WARNING: body fallback fillet failed: {e2}")

    # Nose rounding on front face perimeter (best effort)
    try:
        body = body.faces(fwd_sel).edges().fillet(nose_fillet)
    except Exception as e:
        print(f"WARNING: nose fillet({nose_fillet}) failed: {e}")

    plug_body = neck.union(body)

    # Pin-root recess pockets: create cutters on front plane and subtract
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

    # Pin tip chamfer (best effort)
    try:
        pins = pins.faces(fwd_sel).edges().chamfer(pin_tip_ch)
    except Exception as e:
        print(f"WARNING: pin chamfer({pin_tip_ch}) failed: {e}")

    plug = plug_body.union(pins)

    # Union new plug to trimmed cord
    new_cord_shape = cq.Workplane(obj=trimmed_cord_shape).union(plug).val()

    out_shapes = kept_solids + [new_cord_shape]
    result = cq.Compound.makeCompound(out_shapes)

    out_bb = result.BoundingBox()
    print(f"Result solids in compound: {len(out_shapes)}")
    print(f"Result bbox: x={out_bb.xlen:.2f}, y={out_bb.ylen:.2f}, z={out_bb.zlen:.2f}")

    return cq.Workplane(obj=result)
