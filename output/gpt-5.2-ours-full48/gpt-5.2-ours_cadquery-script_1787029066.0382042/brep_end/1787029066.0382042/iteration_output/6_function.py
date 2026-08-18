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
    xr = max(1e-6, bb.xmax - bb.xmin)
    yr = max(1e-6, bb.ymax - bb.ymin)
    zr = max(1e-6, bb.zmax - bb.zmin)
    print(f"BBOX x:[{bb.xmin:.3f},{bb.xmax:.3f}] y:[{bb.ymin:.3f},{bb.ymax:.3f}] z:[{bb.zmin:.3f},{bb.zmax:.3f}]")
    print(f"Center: ({bb.center.x:.3f}, {bb.center.y:.3f}, {bb.center.z:.3f})")

    # --- Try to infer a reasonable hose nipple OD by sampling cylindrical faces aligned to +/-Y ---
    def _vec_dot(a, b):
        return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]

    cyl_radii_y = []
    for si, s in enumerate(solids):
        try:
            for f in cq.Workplane().add(s).faces().vals():
                try:
                    gt = str(f.geomType()).upper()
                except Exception:
                    gt = ""
                if "CYL" not in gt:
                    continue
                try:
                    ad = f._geomAdaptor()
                    c = ad.Cylinder()
                    r = float(c.Radius())
                    d = c.Axis().Direction()
                    dirv = (float(d.X()), float(d.Y()), float(d.Z()))
                    # axis nearly parallel to Y
                    if abs(_vec_dot(dirv, (0.0, 1.0, 0.0))) > 0.92:
                        if 6.0 < r < 40.0:
                            cyl_radii_y.append(r)
                except Exception:
                    continue
        except Exception:
            continue

    cyl_radii_y.sort()
    if cyl_radii_y:
        # pick upper-middle to bias toward hose necks (not tiny ribs)
        idx = min(len(cyl_radii_y)-1, max(0, int(0.7*len(cyl_radii_y))))
        outer_d = 2.0 * cyl_radii_y[idx]
        outer_d = max(16.0, min(50.0, outer_d))
    else:
        outer_d = 22.0

    inner_d = max(8.0, outer_d * 0.65)

    print(f"=== Port sizing === outer_d={outer_d:.2f} inner_d={inner_d:.2f} (from {len(cyl_radii_y)} cyl faces aligned to Y)")

    # --- Port primitive (hose nipple with bore + bead) ---
    def make_hose_nipple(base_pt, axis_dir, outer_d, inner_d, length=35.0, bead_scale=1.12, bead_len=3.0, bore_extra=2.0):
        ax = cq.Vector(*axis_dir)
        L = math.sqrt(ax.x*ax.x + ax.y*ax.y + ax.z*ax.z)
        if L < 1e-9:
            ax = cq.Vector(0, 1, 0)
        else:
            ax = cq.Vector(ax.x/L, ax.y/L, ax.z/L)

        outer_r = outer_d/2.0
        inner_r = inner_d/2.0
        bead_r = outer_r * bead_scale

        base = cq.Vector(*base_pt)

        outer = cq.Solid.makeCylinder(outer_r, length, base, ax)
        inner = cq.Solid.makeCylinder(inner_r, length + 2*bore_extra, base - ax*bore_extra, ax)
        tube = outer.cut(inner)

        b_len = max(1.5, float(bead_len))
        bead_base = base + ax*(length - b_len)
        bead_outer = cq.Solid.makeCylinder(bead_r, b_len, bead_base, ax)
        bead_inner = cq.Solid.makeCylinder(inner_r, b_len + 2*bore_extra, bead_base - ax*bore_extra, ax)
        bead = bead_outer.cut(bead_inner)

        return tube.fuse(bead)

    def make_bore_cutter(base_pt, axis_dir, inner_d, cut_depth=30.0, extra=6.0):
        # Cut *into* the tank: go opposite the outward axis.
        ax = cq.Vector(*axis_dir)
        L = math.sqrt(ax.x*ax.x + ax.y*ax.y + ax.z*ax.z)
        if L < 1e-9:
            ax = cq.Vector(0, 1, 0)
        else:
            ax = cq.Vector(ax.x/L, ax.y/L, ax.z/L)
        inward = ax.multiply(-1.0)
        r = inner_d/2.0
        base = cq.Vector(*base_pt) + inward*extra
        return cq.Solid.makeCylinder(r, cut_depth + extra, base, inward)

    # --- Choose a target solid by intersection with a small probe around the base area ---
    def pick_target_solid_for_port(base_pt, axis_dir, probe_r=8.0, probe_len=18.0):
        ax = cq.Vector(*axis_dir)
        L = math.sqrt(ax.x*ax.x + ax.y*ax.y + ax.z*ax.z)
        if L < 1e-9:
            ax = cq.Vector(0, 1, 0)
        else:
            ax = cq.Vector(ax.x/L, ax.y/L, ax.z/L)
        # probe extends slightly inward and outward about the base
        base = cq.Vector(*base_pt) - ax*(probe_len*0.4)
        probe = cq.Solid.makeCylinder(probe_r, probe_len, base, ax)

        best_i = None
        best_v = 0.0
        for i, s in enumerate(solids):
            try:
                inter = s.intersect(probe)
                v = float(inter.Volume())
                if v > best_v:
                    best_v = v
                    best_i = i
            except Exception:
                continue

        if best_i is not None and best_v > 1e-3:
            return best_i, best_v

        # Fallback: nearest bbox center distance to base
        bp = cq.Vector(*base_pt)
        best_i = None
        best_d = 1e99
        for i, s in enumerate(solids):
            sb = s.BoundingBox()
            c = sb.center
            d = (c.x - bp.x)**2 + (c.y - bp.y)**2 + (c.z - bp.z)**2
            if d < best_d:
                best_d = d
                best_i = i
        return best_i, 0.0

    # --- Place ports at TOP-RIGHT and BOTTOM-LEFT corners in the 'right' view ---
    # Interpreting: top/bottom => +/-Z, right/left => +/-Y. Ports protrude outward along +/-Y.
    embed = 4.0
    z_margin = max(18.0, 0.10 * zr)
    x_loc = bb.center.x  # keep near mid-thickness to mimic existing side hose features

    outlet_base = (x_loc, bb.ymax - embed, bb.zmax - z_margin)   # top-right
    inlet_base  = (x_loc, bb.ymin + embed, bb.zmin + z_margin)   # bottom-left

    outlet_axis = (0, 1, 0)
    inlet_axis  = (0, -1, 0)

    outlet_port = make_hose_nipple(outlet_base, outlet_axis, outer_d=outer_d, inner_d=inner_d, length=35.0)
    inlet_port  = make_hose_nipple(inlet_base,  inlet_axis,  outer_d=outer_d, inner_d=inner_d, length=35.0)

    outlet_bore = make_bore_cutter(outlet_base, outlet_axis, inner_d=inner_d, cut_depth=32.0)
    inlet_bore  = make_bore_cutter(inlet_base,  inlet_axis,  inner_d=inner_d, cut_depth=32.0)

    print("=== Port placement ===")
    print(f"Outlet (top-right) base: x={outlet_base[0]:.2f} y={outlet_base[1]:.2f} z={outlet_base[2]:.2f} axis=+Y")
    print(f"Inlet  (bot-left) base: x={inlet_base[0]:.2f} y={inlet_base[1]:.2f} z={inlet_base[2]:.2f} axis=-Y")

    # --- Attach ports to the most likely tank solids; avoid unioning the entire assembly (was collapsing solids) ---
    new_solids = list(solids)

    def attach_port_to_solid(port_solid, bore_cutter, base_pt, axis_dir, label):
        nonlocal new_solids
        tgt_i, inter_v = pick_target_solid_for_port(base_pt, axis_dir, probe_r=max(10.0, outer_d*0.6), probe_len=22.0)
        print(f"{label}: target solid idx={tgt_i} probe_intersect_vol={inter_v:.3f}")
        if tgt_i is None:
            # cannot attach; just add as separate
            new_solids.append(port_solid)
            return

        s = new_solids[tgt_i]
        fused = None
        try:
            fused = s.fuse(port_solid)
        except Exception as e:
            print(f"{label}: fuse failed; keeping port as separate solid. Error:", e)
            new_solids.append(port_solid)
            return

        # Try to open the passage into the tank
        try:
            fused = fused.cut(bore_cutter)
        except Exception as e:
            print(f"{label}: bore cut failed (visual port still present). Error:", e)

        new_solids[tgt_i] = fused

    attach_port_to_solid(outlet_port, outlet_bore, outlet_base, outlet_axis, "Outlet")
    attach_port_to_solid(inlet_port,  inlet_bore,  inlet_base,  inlet_axis,  "Inlet")

    result = cq.Compound.makeCompound(new_solids)
    try:
        print("=== Result ===")
        try:
            print("Result valid:", result.isValid())
        except Exception:
            pass
        print("Result solids:", len(list(result.Solids())))
    except Exception:
        pass

    return cq.Workplane().add(result)
