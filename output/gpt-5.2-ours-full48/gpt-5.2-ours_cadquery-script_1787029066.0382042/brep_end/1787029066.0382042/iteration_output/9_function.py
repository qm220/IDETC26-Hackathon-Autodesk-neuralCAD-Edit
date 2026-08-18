def my_cad_function(args):
    import os, math
    import cadquery as cq

    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder

    input_file = os.path.expanduser(args.get("input_file", ""))
    if not input_file or (not os.path.exists(input_file)):
        raise ValueError(f"Missing or invalid args['input_file']: {input_file}")

    shp = cq.importers.importStep(input_file).val()

    print("=== Loaded model ===")
    try:
        print("Valid:", shp.isValid())
    except Exception:
        pass

    try:
        shp = shp.fix()
        print("Healed: True")
        try:
            print("Valid after heal:", shp.isValid())
        except Exception:
            pass
    except Exception as e:
        print("Healed: False (fix() failed/not available):", e)

    solids = list(shp.Solids())
    print("Solids:", len(solids))

    bb = shp.BoundingBox()
    xr = max(1e-6, bb.xmax - bb.xmin)
    yr = max(1e-6, bb.ymax - bb.ymin)
    zr = max(1e-6, bb.zmax - bb.zmin)
    print(f"BBOX x:[{bb.xmin:.3f},{bb.xmax:.3f}] y:[{bb.ymin:.3f},{bb.ymax:.3f}] z:[{bb.zmin:.3f},{bb.zmax:.3f}]")
    print(f"Center: ({bb.center.x:.3f}, {bb.center.y:.3f}, {bb.center.z:.3f})")

    def _unit(v: cq.Vector):
        L = math.sqrt(v.x*v.x + v.y*v.y + v.z*v.z)
        return v if L < 1e-9 else cq.Vector(v.x/L, v.y/L, v.z/L)

    def make_hose_nipple(base_pt, axis_dir, outer_d, inner_d, length, bead_scale=1.10, bead_len=3.0):
        ax = _unit(cq.Vector(*axis_dir))
        base = cq.Vector(*base_pt)
        outer_r = outer_d/2.0
        inner_r = inner_d/2.0
        bead_r = outer_r * float(bead_scale)

        outer = cq.Solid.makeCylinder(outer_r, float(length), base, ax)
        inner = cq.Solid.makeCylinder(inner_r, float(length) + 10.0, base - ax*5.0, ax)
        tube = outer.cut(inner)

        b_len = max(1.5, float(bead_len))
        bead_base = base + ax*(float(length) - b_len)
        bead_outer = cq.Solid.makeCylinder(bead_r, b_len, bead_base, ax)
        bead_inner = cq.Solid.makeCylinder(inner_r, b_len + 10.0, bead_base - ax*5.0, ax)
        bead = bead_outer.cut(bead_inner)

        return tube.fuse(bead)

    def make_bore_cutter(base_pt, axis_dir, inner_d, depth):
        # cut inward opposite to outward axis
        ax = _unit(cq.Vector(*axis_dir))
        inward = ax.multiply(-1.0)
        r = inner_d/2.0
        base = cq.Vector(*base_pt) + inward*2.0
        return cq.Solid.makeCylinder(r, float(depth), base, inward)

    # ----------------------------
    # Try to detect existing end-port cylinders oriented ~Y so we can mirror their X/Z.
    # ----------------------------
    cyls = []
    for f in shp.Faces():
        try:
            ad = BRepAdaptor_Surface(f.wrapped)
            if ad.GetType() != GeomAbs_Cylinder:
                continue
            cyl = ad.Cylinder()
            r = float(cyl.Radius())
            d = cyl.Axis().Direction()
            dv = cq.Vector(d.X(), d.Y(), d.Z())
            if abs(dv.y) < 0.85:
                continue
            if not (2.0 <= r <= 40.0):
                continue
            cen = f.Center()
            fb = f.BoundingBox()
            yspan = fb.ymax - fb.ymin
            if yspan < 5.0:
                continue
            # Prefer cylinders near ends
            near_end = (cen.y > bb.ymax - 0.18*yr) or (cen.y < bb.ymin + 0.18*yr)
            if not near_end:
                continue
            cyls.append({"r": r, "cen": cen, "dir": dv, "yspan": yspan, "area": float(f.Area())})
        except Exception:
            continue

    print(f"Detected ~Y cylinders near ends: {len(cyls)}")

    zmid = bb.center.z
    ymid = bb.center.y

    def pick_ref(side, which):
        # side: 'left' (y<ymid) or 'right' (y>ymid)
        # which: 'top' (z high) or 'bottom' (z low)
        cand = []
        for c in cyls:
            if side == "left" and c["cen"].y >= ymid:
                continue
            if side == "right" and c["cen"].y <= ymid:
                continue
            if which == "top" and c["cen"].z <= zmid + 0.15*zr:
                continue
            if which == "bottom" and c["cen"].z >= zmid - 0.15*zr:
                continue
            cand.append(c)
        if not cand:
            return None
        # choose most "boss-like": larger yspan then area
        cand.sort(key=lambda c: (c["yspan"], c["area"]), reverse=True)
        return cand[0]

    ref_top_left = pick_ref("left", "top")
    ref_bot_right = pick_ref("right", "bottom")

    print("ref_top_left:", None if ref_top_left is None else (ref_top_left["cen"].x, ref_top_left["cen"].y, ref_top_left["cen"].z, 2*ref_top_left["r"]))
    print("ref_bot_right:", None if ref_bot_right is None else (ref_bot_right["cen"].x, ref_bot_right["cen"].y, ref_bot_right["cen"].z, 2*ref_bot_right["r"]))

    # ----------------------------
    # Identify top/bottom header-tank solids as fallback placement references.
    # ----------------------------
    def pick_tank_candidates():
        cands = []
        for i, s in enumerate(solids):
            sb = s.BoundingBox()
            yspan = sb.ymax - sb.ymin
            zspan = sb.zmax - sb.zmin
            xspan = sb.xmax - sb.xmin
            try:
                vol = float(s.Volume())
            except Exception:
                vol = 0.0
            # Header tanks run (mostly) along full Y, but are shallow in Z compared to full assembly.
            if yspan < 0.55*yr:
                continue
            if zspan > 0.45*zr:
                continue
            if xspan < 0.10*xr:
                continue
            if vol < 1e3:
                continue
            cands.append({"i": i, "s": s, "bb": sb, "vol": vol, "yspan": yspan, "zspan": zspan})
        return cands

    tank_cands = pick_tank_candidates()
    print(f"Tank candidates: {len(tank_cands)}")

    def fallback_top_bottom_solids():
        # Fallback: use solids with large Y-span; choose by z-extremes.
        tmp = []
        for i, s in enumerate(solids):
            sb = s.BoundingBox()
            yspan = sb.ymax - sb.ymin
            if yspan < 0.45*yr:
                continue
            try:
                vol = float(s.Volume())
            except Exception:
                vol = 0.0
            tmp.append({"i": i, "s": s, "bb": sb, "vol": vol})
        if not tmp:
            # absolute fallback: choose by z-extremes among all solids
            tmp = [{"i": i, "s": s, "bb": s.BoundingBox(), "vol": float(getattr(s, 'Volume', lambda: 0.0)()) if hasattr(s, 'Volume') else 0.0} for i, s in enumerate(solids)]
        top = max(tmp, key=lambda c: (c["bb"].zmax, c["vol"]))
        bot = min(tmp, key=lambda c: (c["bb"].zmin, -c["vol"]))
        return top, bot

    if tank_cands:
        top_tank = max(tank_cands, key=lambda c: (c["bb"].zmax, c["vol"]))
        bot_tank = min(tank_cands, key=lambda c: (c["bb"].zmin, -c["vol"]))
    else:
        top_tank, bot_tank = fallback_top_bottom_solids()

    print("Top tank idx:", top_tank["i"], "bb.z:", (top_tank["bb"].zmin, top_tank["bb"].zmax), "bb.y:", (top_tank["bb"].ymin, top_tank["bb"].ymax))
    print("Bot tank idx:", bot_tank["i"], "bb.z:", (bot_tank["bb"].zmin, bot_tank["bb"].zmax), "bb.y:", (bot_tank["bb"].ymin, bot_tank["bb"].ymax))

    # ----------------------------
    # Port sizing: use reference cylinder diameter if found; otherwise reasonable defaults.
    # ----------------------------
    outer_d = 22.0
    inner_d = 15.0
    length = 32.0

    if ref_top_left is not None:
        outer_d = max(18.0, min(35.0, float(2.0 * ref_top_left["r"])))
    elif ref_bot_right is not None:
        outer_d = max(18.0, min(35.0, float(2.0 * ref_bot_right["r"])))

    inner_d = max(10.0, min(outer_d - 6.0, inner_d))

    print(f"Port sizing: outer_d={outer_d:.2f} inner_d={inner_d:.2f} length={length:.2f}")

    # ----------------------------
    # Placement (mirror if refs exist; else use tank centers)
    # ----------------------------
    embed = 6.0  # ensure intersection for fuse, and visual attachment even if fuse fails

    # Outlet: TOP-RIGHT end => +Y end of top tank
    if ref_top_left is not None:
        x_out = float(ref_top_left["cen"].x)
        z_out = float(ref_top_left["cen"].z)
    else:
        x_out = float(top_tank["bb"].center.x)
        z_out = float(top_tank["bb"].center.z)
    y_out_end = float(top_tank["bb"].ymax)
    outlet_axis = (0.0, 1.0, 0.0)
    outlet_base = (x_out, y_out_end - embed, z_out)

    # Inlet: BOTTOM-LEFT end => -Y end of bottom tank
    if ref_bot_right is not None:
        x_in = float(ref_bot_right["cen"].x)
        z_in = float(ref_bot_right["cen"].z)
    else:
        x_in = float(bot_tank["bb"].center.x)
        z_in = float(bot_tank["bb"].center.z)
    y_in_end = float(bot_tank["bb"].ymin)
    inlet_axis = (0.0, -1.0, 0.0)
    inlet_base = (x_in, y_in_end + embed, z_in)

    print("Outlet base (top-right):", outlet_base, "axis +Y")
    print("Inlet  base (bot-left):", inlet_base, "axis -Y")

    outlet_port = make_hose_nipple(outlet_base, outlet_axis, outer_d, inner_d, length)
    inlet_port = make_hose_nipple(inlet_base, inlet_axis, outer_d, inner_d, length)

    bore_depth = 45.0
    outlet_bore = make_bore_cutter(outlet_base, outlet_axis, inner_d, depth=bore_depth)
    inlet_bore = make_bore_cutter(inlet_base, inlet_axis, inner_d, depth=bore_depth)

    # ----------------------------
    # Attach: fuse into the selected tank solids; if fuse fails, keep as intersecting separate solids.
    # ----------------------------
    new_solids = list(solids)

    def attach_to(idx, label, port_solid, bore_solid):
        nonlocal new_solids
        tgt = new_solids[idx]
        fused_ok = False
        try:
            tgt2 = tgt.fuse(port_solid)
            fused_ok = True
        except Exception as e:
            print(f"{label}: fuse failed -> keeping port as separate solid. Error: {e}")
            new_solids.append(port_solid)
            return

        # cut bore best-effort
        try:
            tgt2 = tgt2.cut(bore_solid)
        except Exception as e:
            print(f"{label}: bore cut failed (port still present). Error: {e}")

        try:
            tgt2 = tgt2.fix()
        except Exception:
            pass

        new_solids[idx] = tgt2

    attach_to(top_tank["i"], "Outlet", outlet_port, outlet_bore)
    attach_to(bot_tank["i"], "Inlet", inlet_port, inlet_bore)

    result = cq.Compound.makeCompound(new_solids)
    print("=== Result ===")
    try:
        print("Result valid:", result.isValid())
    except Exception:
        pass
    print("Result solids:", len(list(result.Solids())))

    return cq.Workplane().add(result)
