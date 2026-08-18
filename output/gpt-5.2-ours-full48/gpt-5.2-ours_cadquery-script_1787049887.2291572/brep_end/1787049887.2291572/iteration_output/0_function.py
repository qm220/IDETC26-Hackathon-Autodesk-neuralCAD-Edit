def my_cad_function(args):
    import cadquery as cq
    import os, math

    # --- Load STEP ---
    input_file = os.path.expanduser(args.get("input_file", ""))
    model = cq.importers.importStep(input_file)
    shp = model.val() if hasattr(model, "val") else model

    solids = list(shp.Solids())
    print(f"Loaded STEP: {input_file}")
    print(f"Total solids: {len(solids)}")

    overall_bb = shp.BoundingBox()
    overall_center = overall_bb.center
    print(f"Overall bbox center: ({overall_center.x:.3f}, {overall_center.y:.3f}, {overall_center.z:.3f})")

    # --- Utility helpers ---
    def bb_dims(s):
        bb = s.BoundingBox()
        return bb, (bb.xlen, bb.ylen, bb.zlen)

    def max_aspect_candidate(solids):
        """Pick likely cord(+plug) solid: long & thin (high aspect ratio)."""
        best = None
        best_i = None
        best_score = -1
        for i, s in enumerate(solids):
            bb, (dx, dy, dz) = bb_dims(s)
            dims = [dx, dy, dz]
            mx = max(dims)
            mn = max(1e-6, min(dims))
            aspect = mx / mn
            # heuristic: cord is long and thin
            score = aspect
            if mx < 80:
                score *= 0.25
            if mn > 35:
                score *= 0.10
            if mx > 120 and mn < 20:
                score *= 2.0
            if score > best_score:
                best_score = score
                best = s
                best_i = i
        return best_i, best

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
        return (a[0]+b[0], a[1]+b[1], a[2]+b[2])

    def sub(a, b):
        return (a[0]-b[0], a[1]-b[1], a[2]-b[2])

    def mul(a, s):
        return (a[0]*s, a[1]*s, a[2]*s)

    # --- Identify cord(+plug) solid ---
    cord_idx, cord_solid = max_aspect_candidate(solids)
    if cord_solid is None:
        print("No solids found; returning original model")
        return model

    cord_bb, (cdx, cdy, cdz) = bb_dims(cord_solid)
    print(f"Selected cord-like solid index: {cord_idx}")
    print(f"Cord-like bbox lens: dx={cdx:.3f}, dy={cdy:.3f}, dz={cdz:.3f}")

    # Determine primary axis by bbox length
    dims = {"X": cdx, "Y": cdy, "Z": cdz}
    axis = max(dims, key=dims.get)

    # Determine which end is the plug end (farther from overall center along that axis)
    if axis == "X":
        end_max = cord_bb.xmax
        end_min = cord_bb.xmin
        c0 = overall_center.x
        plug_end = end_max if abs(end_max - c0) >= abs(end_min - c0) else end_min
        n = (1.0, 0.0, 0.0) if plug_end == end_max else (-1.0, 0.0, 0.0)
        perp_dims = (cdy, cdz)
    elif axis == "Y":
        end_max = cord_bb.ymax
        end_min = cord_bb.ymin
        c0 = overall_center.y
        plug_end = end_max if abs(end_max - c0) >= abs(end_min - c0) else end_min
        n = (0.0, 1.0, 0.0) if plug_end == end_max else (0.0, -1.0, 0.0)
        perp_dims = (cdx, cdz)
    else:
        end_max = cord_bb.zmax
        end_min = cord_bb.zmin
        c0 = overall_center.z
        plug_end = end_max if abs(end_max - c0) >= abs(end_min - c0) else end_min
        n = (0.0, 0.0, 1.0) if plug_end == end_max else (0.0, 0.0, -1.0)
        perp_dims = (cdx, cdy)

    # Estimate cord diameter from bbox thickness perpendicular to cord axis
    cord_d = max(3.0, min(10.0, min(perp_dims)))

    print(f"Detected cord axis: {axis}, plug_end={plug_end:.3f}, normal n={n}, estimated cord_d={cord_d:.3f}")

    # --- Parameters from operation.json ---
    pin_d = 4.0
    pin_len = 19.0
    pin_spacing = 19.0
    pin_tip_ch = 0.5

    body_w = 35.0
    body_h = 16.0
    body_t = 14.0  # per planning: used as extrusion/length along plug axis
    body_fillet = 2.0

    # realism refinements
    recess_d = 6.5
    recess_depth = 1.0
    side_taper_deg = 1.5
    nose_fillet = 3.0

    # how much of the old end geometry to remove
    cut_off_len = (pin_len + body_t + 25.0)  # generous removal of existing plug
    overlap_into_cord = 1.0
    neck_len = 8.0

    # --- Compute cut plane origin point in 3D ---
    # plug_end is coordinate along the main axis, so convert into point
    if axis == "X":
        cut_coord = plug_end - n[0]*cut_off_len
        cut_origin = (cut_coord, cord_bb.center.y, cord_bb.center.z)
    elif axis == "Y":
        cut_coord = plug_end - n[1]*cut_off_len
        cut_origin = (cord_bb.center.x, cut_coord, cord_bb.center.z)
    else:
        cut_coord = plug_end - n[2]*cut_off_len
        cut_origin = (cord_bb.center.x, cord_bb.center.y, cut_coord)

    # Build a stable xDir for the plane
    # pick a vector not parallel to n
    up = (0.0, 0.0, 1.0)
    if abs(dot(n, up)) > 0.95:
        up = (0.0, 1.0, 0.0)
    xDir = unit(cross(up, n))

    cut_plane = cq.Plane(origin=cq.Vector(*cut_origin), xDir=cq.Vector(*xDir), normal=cq.Vector(*n))

    print(f"Cut plane origin: ({cut_origin[0]:.3f}, {cut_origin[1]:.3f}, {cut_origin[2]:.3f})")

    # --- Trim the cord-like solid by cutting away everything beyond the cut plane toward the plug end ---
    # Create a huge box starting at the cut plane and extending in +normal direction (toward plug)
    cut_tool = cq.Workplane(cut_plane).box(2000, 2000, 2000, centered=(True, True, False))
    trimmed_cord = cq.Workplane(obj=cord_solid).cut(cut_tool).val()

    # --- Attempt to remove any separate "old plug" solids sitting near the far end ---
    # Heuristic: small solids whose bbox center is far along +n from the cut plane.
    kept_solids = []
    removed = []
    cut_o = cut_origin
    for i, s in enumerate(solids):
        if i == cord_idx:
            continue
        bb, (dx, dy, dz) = bb_dims(s)
        mx = max(dx, dy, dz)
        ctr = (bb.center.x, bb.center.y, bb.center.z)
        proj = dot(sub(ctr, cut_o), n)  # positive means beyond cut plane toward plug end
        # likely old plug candidates are close to the cord end and small-ish
        if proj > 5.0 and mx < 120.0:
            removed.append(i)
        else:
            kept_solids.append(s)

    print(f"Removed candidate plug solids indices (heuristic): {removed}")

    # --- Build new Europlug at the cut plane ---
    # We'll start slightly *into* the trimmed cord for a reliable union
    base_origin = add(cut_o, mul(n, -overlap_into_cord))
    base_plane = cq.Plane(origin=cq.Vector(*base_origin), xDir=cq.Vector(*xDir), normal=cq.Vector(*n))

    # Rear profile plane for body start (after neck)
    rear_origin = add(base_origin, mul(n, neck_len))
    rear_plane = cq.Plane(origin=cq.Vector(*rear_origin), xDir=cq.Vector(*xDir), normal=cq.Vector(*n))

    # Front plane for pins
    front_origin = add(rear_origin, mul(n, body_t))
    front_plane = cq.Plane(origin=cq.Vector(*front_origin), xDir=cq.Vector(*xDir), normal=cq.Vector(*n))

    # Neck: loft from circle (cord) -> rounded-rect (body rear)
    neck = (
        cq.Workplane(base_plane)
        .circle(cord_d/2.0)
        .workplane(offset=neck_len)
        .roundedRect(body_w, body_h, body_fillet)
        .loft(combine=True)
    )

    # Body: mild side taper (rear slightly larger than front)
    # compute reduction based on taper
    red = 2.0 * body_t * math.tan(math.radians(side_taper_deg))
    front_w = max(10.0, body_w - red)
    front_h = max(8.0, body_h - 0.6*red)

    body = (
        cq.Workplane(rear_plane)
        .roundedRect(body_w, body_h, body_fillet)
        .workplane(offset=body_t)
        .roundedRect(front_w, front_h, max(0.5, body_fillet - 0.5))
        .loft(combine=True)
    )

    plug = neck.union(body)

    # Pin root recess (pockets on the front face)
    pin_off = pin_spacing / 2.0
    plug = (
        plug
        .workplane(front_plane)
        .pushPoints([(-pin_off, 0.0), (pin_off, 0.0)])
        .circle(recess_d/2.0)
        .cutBlind(-recess_depth)
    )

    # Pins
    pins = (
        cq.Workplane(front_plane)
        .pushPoints([(-pin_off, 0.0), (pin_off, 0.0)])
        .circle(pin_d/2.0)
        .extrude(pin_len)
    )

    # Chamfer pin tips (best-effort): select far face along n's dominant global axis
    # (if n isn't aligned with a global axis, this may not chamfer; we print debug)
    nx, ny, nz = n
    dominant = max([(abs(nx), 'X', nx), (abs(ny), 'Y', ny), (abs(nz), 'Z', nz)], key=lambda t: t[0])
    dom_axis = dominant[1]
    dom_sign = dominant[2]
    face_sel = f">{dom_axis}" if dom_sign > 0 else f"<{dom_axis}"
    print(f"Pin tip chamfer selection: face_sel={face_sel} (n={n})")
    try:
        pins = pins.faces(face_sel).edges().chamfer(pin_tip_ch)
    except Exception as e:
        print(f"WARNING: pin chamfer failed: {e}")

    plug = plug.union(pins)

    # Nose rounding (best-effort fillet)
    try:
        plug = plug.edges().fillet(body_fillet)
    except Exception as e:
        print(f"WARNING: body fillet({body_fillet}) failed: {e}")

    try:
        plug = plug.faces(face_sel).edges().fillet(nose_fillet)
    except Exception as e:
        print(f"WARNING: nose fillet({nose_fillet}) failed: {e}")

    # Union plug to trimmed cord
    new_cord = cq.Workplane(obj=trimmed_cord).union(plug).val()

    # --- Rebuild final compound ---
    out_shapes = kept_solids + [new_cord]
    result = cq.Compound.makeCompound(out_shapes)

    # Final debug
    out_bb = result.BoundingBox()
    print(f"Result solids in compound: {len(out_shapes)}")
    print(f"Result bbox: x={out_bb.xlen:.2f}, y={out_bb.ylen:.2f}, z={out_bb.zlen:.2f}")

    return cq.Workplane(obj=result)
