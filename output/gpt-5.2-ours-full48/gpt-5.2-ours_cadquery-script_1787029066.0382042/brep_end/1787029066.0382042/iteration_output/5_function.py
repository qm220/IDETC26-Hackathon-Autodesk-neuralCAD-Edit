def my_cad_function(args):
    import os, math
    import cadquery as cq

    input_file = os.path.expanduser(args.get("input_file", ""))
    if not input_file or (not os.path.exists(input_file)):
        raise ValueError(f"Missing or invalid args['input_file']: {input_file}")

    shape = cq.importers.importStep(input_file).val()

    print("=== Loaded model ===")
    try:
        print("Valid:", shape.isValid())
    except Exception:
        pass

    solids = list(shape.Solids())
    print("Solids:", len(solids))
    bb = shape.BoundingBox()
    print(f"BBOX x:[{bb.xmin:.3f},{bb.xmax:.3f}] y:[{bb.ymin:.3f},{bb.ymax:.3f}] z:[{bb.zmin:.3f},{bb.zmax:.3f}]")
    print(f"Center: ({bb.center.x:.3f}, {bb.center.y:.3f}, {bb.center.z:.3f})")

    xr = max(1e-6, bb.xmax - bb.xmin)
    yr = max(1e-6, bb.ymax - bb.ymin)
    zr = max(1e-6, bb.zmax - bb.zmin)

    def sbb(s):
        return s.BoundingBox()

    def dims(sb):
        return (sb.xmax - sb.xmin, sb.ymax - sb.ymin, sb.zmax - sb.zmin)

    def vol(s):
        try:
            return float(s.Volume())
        except Exception:
            return 0.0

    # --- Find likely top/bottom header tank solids (coarse heuristics) ---
    # Tanks should be near global top/bottom in Z and span a large portion of Y width.
    top_candidates = []
    bot_candidates = []
    for i, s in enumerate(solids):
        sb = sbb(s)
        dx, dy, dz = dims(sb)
        if dy < 0.60 * yr:
            continue
        if dz < 8:
            continue
        if sb.zmax > bb.zmax - 0.10 * zr:
            top_candidates.append((i, s, sb, vol(s)))
        if sb.zmin < bb.zmin + 0.10 * zr:
            bot_candidates.append((i, s, sb, vol(s)))

    top_candidates.sort(key=lambda t: t[3], reverse=True)
    bot_candidates.sort(key=lambda t: t[3], reverse=True)

    top_tank = top_candidates[0] if top_candidates else None
    bot_tank = bot_candidates[0] if bot_candidates else None

    print("=== Tank candidate detection ===")
    if top_tank:
        i, s, sb, v = top_tank
        dx, dy, dz = dims(sb)
        print(f"Top tank cand idx={i} vol={v:.1f} dims=({dx:.1f},{dy:.1f},{dz:.1f}) y=({sb.ymin:.1f},{sb.ymax:.1f}) z=({sb.zmin:.1f},{sb.zmax:.1f})")
    else:
        print("Top tank cand: NOT FOUND (will still place using global bbox)")

    if bot_tank:
        i, s, sb, v = bot_tank
        dx, dy, dz = dims(sb)
        print(f"Bottom tank cand idx={i} vol={v:.1f} dims=({dx:.1f},{dy:.1f},{dz:.1f}) y=({sb.ymin:.1f},{sb.ymax:.1f}) z=({sb.zmin:.1f},{sb.zmax:.1f})")
    else:
        print("Bottom tank cand: NOT FOUND (will still place using global bbox)")

    # --- Port primitive (hose nipple with bore + small bead) ---
    def make_hose_nipple(base_pt, axis_dir, outer_d=22.0, inner_d=14.0, length=35.0, bead_scale=1.12, bead_len=3.0, bore_extra=2.0):
        # base_pt: start point of nipple at/inside tank wall. Axis points outward.
        ax = cq.Vector(*axis_dir)
        L = math.sqrt(ax.x * ax.x + ax.y * ax.y + ax.z * ax.z)
        if L < 1e-9:
            ax = cq.Vector(1, 0, 0)
        else:
            ax = cq.Vector(ax.x / L, ax.y / L, ax.z / L)

        outer_r = outer_d / 2.0
        inner_r = inner_d / 2.0
        bead_r = outer_r * bead_scale

        base = cq.Vector(*base_pt)

        outer = cq.Solid.makeCylinder(outer_r, length, base, ax)
        inner = cq.Solid.makeCylinder(inner_r, length + 2 * bore_extra, base - ax * bore_extra, ax)
        tube = outer.cut(inner)

        b_len = max(1.5, float(bead_len))
        bead_base = base + ax * (length - b_len)
        bead_outer = cq.Solid.makeCylinder(bead_r, b_len, bead_base, ax)
        bead_inner = cq.Solid.makeCylinder(inner_r, b_len + 2 * bore_extra, bead_base - ax * bore_extra, ax)
        bead = bead_outer.cut(bead_inner)

        # fuse tube + bead (Shape.fuse works on Solids)
        port = tube.fuse(bead)
        return port

    ports = []

    # Placement offsets (kept conservative, away from extreme corners)
    embed = 4.0

    # TOP-RIGHT outlet: high Z, +Y side, axis +Y
    if top_tank:
        _, _, tsb, _ = top_tank
        tx = tsb.center.x
        tdz = (tsb.zmax - tsb.zmin)
        tz = tsb.zmax - 0.35 * tdz
        y_surface = tsb.ymax
    else:
        tx = bb.center.x
        tz = bb.zmax - 0.10 * zr
        y_surface = bb.ymax

    # clamp X/Z within global bbox margins
    tx = max(bb.xmin + 0.15 * xr, min(bb.xmax - 0.15 * xr, tx))
    tz = max(bb.zmin + 0.05 * zr, min(bb.zmax - 0.05 * zr, tz))

    outlet_base = (tx, y_surface - embed, tz)
    outlet = make_hose_nipple(outlet_base, axis_dir=(0, 1, 0), outer_d=22.0, inner_d=14.0, length=35.0)
    ports.append(outlet)
    print(f"Outlet port base @ (x={outlet_base[0]:.2f}, y={outlet_base[1]:.2f}, z={outlet_base[2]:.2f}) axis=+Y")

    # BOTTOM-LEFT inlet: low Z, -Y side, axis -Y
    if bot_tank:
        _, _, bsb, _ = bot_tank
        bx = bsb.center.x
        bdz = (bsb.zmax - bsb.zmin)
        bz = bsb.zmin + 0.35 * bdz
        y_surface2 = bsb.ymin
    else:
        bx = bb.center.x
        bz = bb.zmin + 0.10 * zr
        y_surface2 = bb.ymin

    bx = max(bb.xmin + 0.15 * xr, min(bb.xmax - 0.15 * xr, bx))
    bz = max(bb.zmin + 0.05 * zr, min(bb.zmax - 0.05 * zr, bz))

    inlet_base = (bx, y_surface2 + embed, bz)
    inlet = make_hose_nipple(inlet_base, axis_dir=(0, -1, 0), outer_d=22.0, inner_d=14.0, length=35.0)
    ports.append(inlet)
    print(f"Inlet port base @ (x={inlet_base[0]:.2f}, y={inlet_base[1]:.2f}, z={inlet_base[2]:.2f}) axis=-Y")

    # --- Combine with original ---
    # Try boolean union onto the imported assembly; if it fails (invalid base), fall back to a compound.
    result_shape = None
    try:
        wp = cq.Workplane().add(shape)
        for p in ports:
            wp = wp.union(cq.Workplane().add(p))
        result_shape = wp.val()
        print("=== Boolean union completed ===")
    except Exception as e:
        print("Boolean union failed; returning as compound with separate port solids. Error:", e)
        out_solids = solids + ports
        result_shape = cq.Compound.makeCompound(out_solids)

    try:
        print("Result valid:", result_shape.isValid())
    except Exception:
        pass
    print("Result solids:", len(list(result_shape.Solids())))

    return cq.Workplane().add(result_shape)
