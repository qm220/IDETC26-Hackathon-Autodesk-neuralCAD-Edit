def my_cad_function(args):
    import os, math
    import cadquery as cq

    # OCP helpers (CadQuery uses OCP)
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

    # Heal best-effort
    try:
        shp = shp.fix()
        print("Healed: True")
        try:
            print("Valid after heal:", shp.isValid())
        except Exception:
            pass
    except Exception as e:
        print("Healed: False (fix() not available/failed):", e)

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
        inner = cq.Solid.makeCylinder(inner_r, float(length) + 8.0, base - ax*4.0, ax)
        tube = outer.cut(inner)

        b_len = max(1.5, float(bead_len))
        bead_base = base + ax*(float(length) - b_len)
        bead_outer = cq.Solid.makeCylinder(bead_r, b_len, bead_base, ax)
        bead_inner = cq.Solid.makeCylinder(inner_r, b_len + 8.0, bead_base - ax*4.0, ax)
        bead = bead_outer.cut(bead_inner)

        return tube.fuse(bead)

    def make_bore_cutter(base_pt, axis_dir, inner_d, depth):
        # cut inward opposite outward axis
        ax = _unit(cq.Vector(*axis_dir))
        inward = ax.multiply(-1.0)
        r = inner_d/2.0
        base = cq.Vector(*base_pt) + inward*2.0
        return cq.Solid.makeCylinder(r, float(depth), base, inward)

    # --- Detect existing port-like cylinders oriented ~Y, to mirror placement (z/x) robustly ---
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
            # axis ~ +/-Y
            if abs(dv.y) < 0.92:
                continue
            # reject huge cylinders (fans etc) by radius bounds
            if not (6.0 <= r <= 18.0):
                continue

            cen = f.Center()
            fb = f.BoundingBox()
            yspan = fb.ymax - fb.ymin
            if yspan < 10.0:
                continue

            cyls.append({
                "face": f,
                "r": r,
                "dir": dv,
                "cen": cen,
                "bb": fb,
                "yspan": yspan,
                "area": float(f.Area())
            })
        except Exception:
            continue

    print(f"Detected Y-axis cylindrical faces (port candidates): {len(cyls)}")

    ymid = bb.center.y
    zmid = bb.center.z

    def pick_existing_port(side: str, which: str):
        # side: 'left' means y<ymid, 'right' means y>ymid
        # which: 'top' means z>zmid, 'bottom' means z<zmid
        subset = []
        for c in cyls:
            if side == "left" and c["cen"].y >= ymid:
                continue
            if side == "right" and c["cen"].y <= ymid:
                continue
            if which == "top" and c["cen"].z <= zmid:
                continue
            if which == "bottom" and c["cen"].z >= zmid:
                continue
            subset.append(c)

        if not subset:
            return None

        # find extreme z group (top=max, bottom=min)
        zext = max(c["cen"].z for c in subset) if which == "top" else min(c["cen"].z for c in subset)
        near = [c for c in subset if abs(c["cen"].z - zext) < 25.0]
        if not near:
            near = subset

        # choose the one that looks most like the main boss cylinder: largest yspan then area
        near.sort(key=lambda c: (c["yspan"], c["area"]), reverse=True)
        return near[0]

    # Existing reference ports:
    # - outlet should mirror existing TOP-LEFT port -> use its x/z
    # - inlet should mirror existing BOTTOM-RIGHT port -> use its x/z
    ref_top_left = pick_existing_port("left", "top")
    ref_bot_right = pick_existing_port("right", "bottom")

    def infer_inner_d(outer_ref):
        if outer_ref is None:
            return None
        outer_r = outer_ref["r"]
        cx, cz = outer_ref["cen"].x, outer_ref["cen"].z
        # find a smaller coaxial cylinder near same x/z
        inner = None
        for c in cyls:
            if abs(c["cen"].x - cx) > 3.0:
                continue
            if abs(c["cen"].z - cz) > 3.0:
                continue
            if c["r"] >= outer_r * 0.92:
                continue
            if inner is None or c["r"] > inner["r"]:
                inner = c
        return (2.0 * inner["r"]) if inner else None

    # Default sizing fallback
    fallback_outer_d = float(max(18.0, min(28.0, 0.06 * min(yr, zr))))
    fallback_inner_d = float(max(10.0, min(fallback_outer_d * 0.70, fallback_outer_d - 6.0)))
    fallback_len = 32.0

    # Infer sizing from references if possible
    outer_d = fallback_outer_d
    length = fallback_len
    if ref_top_left is not None:
        outer_d = float(2.0 * ref_top_left["r"])
        # approximate length from y-span of cylinder face
        length = float(max(20.0, min(60.0, ref_top_left["yspan"])))

    inner_d = infer_inner_d(ref_top_left) or infer_inner_d(ref_bot_right)
    if inner_d is None:
        inner_d = max(10.0, min(outer_d * 0.70, outer_d - 6.0))
    inner_d = float(inner_d)

    print(f"=== Port sizing (inferred) === outer_d={outer_d:.2f} inner_d={inner_d:.2f} length={length:.2f}")

    # Placement
    embed = 2.5  # ensure overlap for fuse

    # Determine z locations from detected reference ports (prevents using bb.zmax which is distorted by filler neck)
    if ref_top_left is not None:
        z_out = float(ref_top_left["cen"].z)
        x_out = float(ref_top_left["cen"].x)
    else:
        # fallback: place slightly below global max
        z_out = float(bb.zmax - 0.10 * zr)
        x_out = float(bb.center.x)

    if ref_bot_right is not None:
        z_in = float(ref_bot_right["cen"].z)
        x_in = float(ref_bot_right["cen"].x)
    else:
        z_in = float(bb.zmin + 0.10 * zr)
        x_in = float(bb.center.x)

    # Right end is +Y (bb.ymax), left end is -Y (bb.ymin)
    outlet_axis = (0.0, 1.0, 0.0)   # outward +Y
    inlet_axis  = (0.0, -1.0, 0.0)  # outward -Y

    outlet_base = (x_out, bb.ymax - embed, z_out)  # TOP-RIGHT target
    inlet_base  = (x_in,  bb.ymin + embed, z_in)   # BOTTOM-LEFT target

    print("=== Port placement (mirroring existing ports) ===")
    print("ref_top_left:", (None if ref_top_left is None else (ref_top_left["cen"].x, ref_top_left["cen"].y, ref_top_left["cen"].z)))
    print("ref_bot_right:", (None if ref_bot_right is None else (ref_bot_right["cen"].x, ref_bot_right["cen"].y, ref_bot_right["cen"].z)))
    print(f"Outlet base (top-right): x={outlet_base[0]:.2f} y={outlet_base[1]:.2f} z={outlet_base[2]:.2f} axis=+Y")
    print(f"Inlet  base (bot-left): x={inlet_base[0]:.2f} y={inlet_base[1]:.2f} z={inlet_base[2]:.2f} axis=-Y")

    outlet_port = make_hose_nipple(outlet_base, outlet_axis, outer_d, inner_d, length=length)
    inlet_port  = make_hose_nipple(inlet_base,  inlet_axis,  outer_d, inner_d, length=length)

    # Bore depth: make it long enough to break into header volume
    bore_depth = float(max(18.0, min(45.0, length * 0.85)))
    outlet_bore = make_bore_cutter(outlet_base, outlet_axis, inner_d, depth=bore_depth)
    inlet_bore  = make_bore_cutter(inlet_base,  inlet_axis,  inner_d, depth=bore_depth)

    def pick_target_solid(base_pt, axis_dir, want=None):
        ax = _unit(cq.Vector(*axis_dir))
        bp = cq.Vector(*base_pt)

        # larger probe to ensure we hit the tank solid
        probe_r = max(outer_d * 0.80, 12.0)
        probe_len = 80.0
        probe_base = bp - ax*(probe_len*0.65)
        probe = cq.Solid.makeCylinder(probe_r, probe_len, probe_base, ax)

        best_i, best_v = None, 0.0

        # Optional top/bottom preference by bbox
        for i, s in enumerate(solids):
            if want == "top":
                if s.BoundingBox().zmax < (bb.zmin + 0.55*zr):
                    continue
            if want == "bottom":
                if s.BoundingBox().zmin > (bb.zmin + 0.45*zr):
                    continue
            try:
                v = float(s.intersect(probe).Volume())
            except Exception:
                v = 0.0
            if v > best_v:
                best_v = v
                best_i = i

        # Fallback: any solid
        if best_i is None or best_v < 1e-3:
            best_i, best_v = None, 0.0
            for i, s in enumerate(solids):
                try:
                    v = float(s.intersect(probe).Volume())
                except Exception:
                    v = 0.0
                if v > best_v:
                    best_v = v
                    best_i = i

        return best_i, best_v

    new_solids = list(solids)

    def attach(label, port_solid, bore_solid, base_pt, axis_dir, want=None):
        nonlocal new_solids
        ti, iv = pick_target_solid(base_pt, axis_dir, want=want)
        print(f"{label}: picked target solid idx={ti} probe_intersect_vol={iv:.3f}")
        if ti is None or iv < 1e-3:
            print(f"{label}: WARNING no intersecting target found; adding port as separate solid")
            new_solids.append(port_solid)
            return

        tgt = new_solids[ti]

        # Fuse (best-effort)
        try:
            fused = tgt.fuse(port_solid)
        except Exception as e:
            print(f"{label}: fuse failed; adding port as separate solid. Error:", e)
            new_solids.append(port_solid)
            return

        # Cut bore (best-effort)
        try:
            fused = fused.cut(bore_solid)
        except Exception as e:
            print(f"{label}: bore cut failed (port still added). Error:", e)

        # Heal fused solid best-effort
        try:
            fused = fused.fix()
        except Exception:
            pass

        new_solids[ti] = fused

    attach("Outlet", outlet_port, outlet_bore, outlet_base, outlet_axis, want="top")
    attach("Inlet",  inlet_port,  inlet_bore,  inlet_base,  inlet_axis,  want="bottom")

    result = cq.Compound.makeCompound(new_solids)
    print("=== Result ===")
    try:
        print("Result valid:", result.isValid())
    except Exception:
        pass
    print("Result solids:", len(list(result.Solids())))

    return cq.Workplane().add(result)
