def my_cad_function(args):
    import os, math
    import cadquery as cq

    input_file = os.path.expanduser(args.get("input_file", ""))
    if not input_file or (not os.path.exists(input_file)):
        raise ValueError(f"Missing or invalid args['input_file']: {input_file}")

    shp = cq.importers.importStep(input_file).val()

    print("=== Loaded model ===")
    try:
        print("Valid:", shp.isValid())
    except Exception:
        pass

    # Try to heal if possible (imported STEP may be invalid)
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

    # ---- Parameters (kept conservative/typical for hose nipples) ----
    # Prior attempt couldn't reliably infer cylinder radii from faces; use bbox-based heuristic.
    outer_d = float(max(18.0, min(28.0, 0.06 * min(yr, zr))))  # ~22mm for this model
    inner_d = float(max(10.0, min(outer_d * 0.70, outer_d - 6.0)))
    length = 32.0
    embed = 3.0  # how far the nipple starts inside the tank to guarantee overlap

    header_thk = float(max(25.0, min(70.0, 0.07 * zr)))  # estimate top/bottom header vertical thickness

    print(f"=== Port sizing === outer_d={outer_d:.2f} inner_d={inner_d:.2f} length={length:.2f} header_thk~{header_thk:.2f}")

    def _unit(v):
        L = math.sqrt(v.x*v.x + v.y*v.y + v.z*v.z)
        return v if L < 1e-9 else cq.Vector(v.x/L, v.y/L, v.z/L)

    def make_hose_nipple(base_pt, axis_dir, outer_d, inner_d, length=32.0, bead_scale=1.10, bead_len=3.0):
        ax = _unit(cq.Vector(*axis_dir))
        base = cq.Vector(*base_pt)
        outer_r = outer_d/2.0
        inner_r = inner_d/2.0
        bead_r = outer_r * bead_scale

        outer = cq.Solid.makeCylinder(outer_r, length, base, ax)
        inner = cq.Solid.makeCylinder(inner_r, length + 6.0, base - ax*3.0, ax)
        tube = outer.cut(inner)

        b_len = max(1.5, float(bead_len))
        bead_base = base + ax*(length - b_len)
        bead_outer = cq.Solid.makeCylinder(bead_r, b_len, bead_base, ax)
        bead_inner = cq.Solid.makeCylinder(inner_r, b_len + 6.0, bead_base - ax*3.0, ax)
        bead = bead_outer.cut(bead_inner)

        return tube.fuse(bead)

    def make_bore_cutter(base_pt, axis_dir, inner_d, depth):
        # Cut inward opposite to the outward axis
        ax = _unit(cq.Vector(*axis_dir))
        inward = ax.multiply(-1.0)
        r = inner_d/2.0
        # start slightly inside to avoid coincident faces
        base = cq.Vector(*base_pt) + inward*2.0
        return cq.Solid.makeCylinder(r, max(8.0, float(depth)), base, inward)

    def pick_target_solid(base_pt, axis_dir, want="top"):
        """Pick solid that both intersects a probe and matches top/bottom header region."""
        ax = _unit(cq.Vector(*axis_dir))
        bp = cq.Vector(*base_pt)

        probe_r = max(outer_d*0.70, 10.0)
        probe_len = 26.0
        probe_base = bp - ax*(probe_len*0.55)
        probe = cq.Solid.makeCylinder(probe_r, probe_len, probe_base, ax)

        z_top_thresh = bb.zmax - header_thk*1.25
        z_bot_thresh = bb.zmin + header_thk*1.25

        best_i = None
        best_v = 0.0

        # First pass: enforce top/bottom region constraint
        for i, s in enumerate(solids):
            sb = s.BoundingBox()
            if want == "top":
                if sb.zmax < z_top_thresh:
                    continue
            elif want == "bottom":
                if sb.zmin > z_bot_thresh:
                    continue
            try:
                v = float(s.intersect(probe).Volume())
            except Exception:
                v = 0.0
            if v > best_v:
                best_v = v
                best_i = i

        # Fallback: any solid by intersection
        if best_i is None or best_v < 1e-3:
            best_i = None
            best_v = 0.0
            for i, s in enumerate(solids):
                try:
                    v = float(s.intersect(probe).Volume())
                except Exception:
                    v = 0.0
                if v > best_v:
                    best_v = v
                    best_i = i

        return best_i, best_v

    # ---- Placement: interpret right/left as +/-Y, top/bottom as +/-Z, ports protrude along +/-Y ----
    x_loc = bb.center.x
    z_top = bb.zmax - header_thk*0.5
    z_bot = bb.zmin + header_thk*0.5

    outlet_base = (x_loc, bb.ymax - embed, z_top)   # TOP-RIGHT => +Y, +Z
    inlet_base  = (x_loc, bb.ymin + embed, z_bot)   # BOTTOM-LEFT => -Y, -Z

    outlet_axis = (0.0, 1.0, 0.0)
    inlet_axis  = (0.0, -1.0, 0.0)

    print("=== Port placement ===")
    print(f"Outlet base (top-right): x={outlet_base[0]:.2f} y={outlet_base[1]:.2f} z={outlet_base[2]:.2f} axis=+Y")
    print(f"Inlet  base (bot-left): x={inlet_base[0]:.2f} y={inlet_base[1]:.2f} z={inlet_base[2]:.2f} axis=-Y")

    outlet_port = make_hose_nipple(outlet_base, outlet_axis, outer_d, inner_d, length=length)
    inlet_port  = make_hose_nipple(inlet_base,  inlet_axis,  outer_d, inner_d, length=length)

    # Bore depth sized to likely wall thickness; keep moderate to reduce boolean failures
    bore_depth = min(22.0, max(12.0, header_thk*0.45))
    outlet_bore = make_bore_cutter(outlet_base, outlet_axis, inner_d, depth=bore_depth)
    inlet_bore  = make_bore_cutter(inlet_base,  inlet_axis,  inner_d, depth=bore_depth)

    new_solids = list(solids)

    def attach(label, port_solid, bore_solid, base_pt, axis_dir, want):
        nonlocal new_solids
        ti, iv = pick_target_solid(base_pt, axis_dir, want=want)
        print(f"{label}: picked target solid idx={ti} probe_intersect_vol={iv:.3f}")
        if ti is None or iv < 1e-3:
            print(f"{label}: WARNING no intersecting target found; adding port as separate solid")
            new_solids.append(port_solid)
            return

        tgt = new_solids[ti]

        # Fuse
        try:
            fused = tgt.fuse(port_solid)
        except Exception as e:
            print(f"{label}: fuse failed; adding port as separate solid. Error:", e)
            new_solids.append(port_solid)
            return

        # Cut bore (best-effort)
        try:
            fused2 = fused.cut(bore_solid)
            fused = fused2
        except Exception as e:
            print(f"{label}: bore cut failed (port still added). Error:", e)

        # Try heal fused solid
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
