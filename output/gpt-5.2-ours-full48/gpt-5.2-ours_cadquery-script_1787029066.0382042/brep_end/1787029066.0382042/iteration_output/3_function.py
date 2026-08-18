def my_cad_function(args):
    import os, math
    import cadquery as cq

    input_file = os.path.expanduser(args.get("input_file", ""))
    if not input_file or (not os.path.exists(input_file)):
        raise ValueError(f"Missing or invalid args['input_file']: {input_file}")

    asm = cq.importers.importStep(input_file)
    shp = asm.val()

    print("=== Loaded model ===")
    try:
        print("Valid:", shp.isValid())
    except Exception:
        pass

    solids = list(shp.Solids())
    print("Solids:", len(solids))
    bb = shp.BoundingBox()
    print(f"BBOX x:[{bb.xmin:.3f},{bb.xmax:.3f}] y:[{bb.ymin:.3f},{bb.ymax:.3f}] z:[{bb.zmin:.3f},{bb.zmax:.3f}]")
    print(f"Center: ({bb.center.x:.3f}, {bb.center.y:.3f}, {bb.center.z:.3f})")

    # Coordinate convention inferred from provided renders:
    # right-view shows Y to the right and Z up. So:
    #   top = +Z, bottom = -Z, right = +Y, left = -Y
    midY = bb.center.y
    midZ = bb.center.z
    yr = max(1e-6, bb.ymax - bb.ymin)
    zr = max(1e-6, bb.zmax - bb.zmin)

    XAX = cq.Vector(1, 0, 0)

    def unit(v: cq.Vector):
        L = math.sqrt(v.x*v.x + v.y*v.y + v.z*v.z)
        if L < 1e-12:
            return cq.Vector(0, 0, 0)
        return cq.Vector(v.x/L, v.y/L, v.z/L)

    def dot(a: cq.Vector, b: cq.Vector):
        return a.x*b.x + a.y*b.y + a.z*b.z

    def vmul(a: cq.Vector, s: float):
        return cq.Vector(a.x*s, a.y*s, a.z*s)

    def vadd(a: cq.Vector, b: cq.Vector):
        return cq.Vector(a.x+b.x, a.y+b.y, a.z+b.z)

    def vsub(a: cq.Vector, b: cq.Vector):
        return cq.Vector(a.x-b.x, a.y-b.y, a.z-b.z)

    # --- Find existing port-like cylinders (axis ~ X), near corners in YZ ---
    cyls = []
    try:
        from OCP.GeomAbs import GeomAbs_Cylinder
        for f in shp.Faces():
            try:
                ad = f._geomAdaptor()
                if ad.GetType() != GeomAbs_Cylinder:
                    continue
                cy = ad.Cylinder()
                r = float(cy.Radius())
                ax = cy.Axis()
                d = ax.Direction()
                dirv = unit(cq.Vector(d.X(), d.Y(), d.Z()))

                # cylindrical faces aligned with X (ports / fan motors)
                if abs(dot(dirv, XAX)) < 0.97:
                    continue

                # eliminate very large radii (guards, etc.) and too tiny fillets
                if not (4.0 <= r <= 26.0):
                    continue

                c = f.Center()

                # eliminate central region where fan motor/hub cylinders occur
                if abs(c.y - midY) < 0.22 * yr and abs(c.z - midZ) < 0.22 * zr:
                    continue

                fb = f.BoundingBox()
                est_len = float(fb.xmax - fb.xmin)
                cyls.append({
                    "face": f,
                    "center": cq.Vector(c.x, c.y, c.z),
                    "dir": dirv,
                    "r": r,
                    "len": est_len,
                })
            except Exception:
                continue
    except Exception as e:
        print("WARNING: Cylinder scan failed:", e)

    print(f"Detected candidate X-axis cylinders (port-like): {len(cyls)}")
    for i, t in enumerate(sorted(cyls, key=lambda k: (-abs(k['center'].z-midZ), -abs(k['center'].y-midY), -k['r']))[:10]):
        cc = t["center"]
        print(f"  cand[{i}] c=({cc.x:.2f},{cc.y:.2f},{cc.z:.2f}) r={t['r']:.2f} len~{t['len']:.2f}")

    def pick_quadrant(which: str):
        # which: 'top_left' or 'bottom_right'
        best = None
        best_score = -1e9
        for t in cyls:
            c = t["center"]
            if which == "top_left":
                if not (c.y < midY and c.z > midZ):
                    continue
                score = ((midY - c.y) / yr) + ((c.z - midZ) / zr) + 0.05 * (t["r"])
            elif which == "bottom_right":
                if not (c.y > midY and c.z < midZ):
                    continue
                score = ((c.y - midY) / yr) + ((midZ - c.z) / zr) + 0.05 * (t["r"])
            else:
                continue

            if score > best_score:
                best_score = score
                best = t
        return best

    src_top_left = pick_quadrant("top_left")
    src_bot_right = pick_quadrant("bottom_right")

    if src_top_left is None or src_bot_right is None:
        print("WARNING: Could not find both reference ports by cylinder detection.")

    def find_inner_radius(src):
        if src is None:
            return None
        c0 = src["center"]
        r0 = src["r"]
        # Look for a smaller concentric cylinder close in YZ (same port bore)
        best = None
        for t in cyls:
            if t is src:
                continue
            c = t["center"]
            if abs(c.y - c0.y) > 2.5:
                continue
            if abs(c.z - c0.z) > 2.5:
                continue
            if abs(c.x - c0.x) > 6.0:
                continue
            if not (t["r"] < r0 - 0.8):
                continue
            if best is None or t["r"] < best:
                best = t["r"]
        return best

    def choose_outdir_from_src(src_center: cq.Vector, src_dir: cq.Vector):
        # Determine which X direction is outward based on where the face center lies.
        # Ports appear on the +X side in the provided renders (xmax ~ 12.7), but use robust sign.
        guess = XAX if (src_center.x > bb.center.x) else cq.Vector(-1, 0, 0)
        # if cylinder axis points opposite, flip
        if dot(src_dir, guess) < 0:
            guess = vmul(guess, -1)
        return unit(guess)

    def make_boss_and_hole(target_center: cq.Vector, outdir: cq.Vector, outer_r: float, inner_r: float, boss_len: float):
        boss_len = float(max(10.0, min(80.0, boss_len if boss_len > 2.0 else 26.0)))
        # Make boss a bit longer so it certainly intersects the tank body
        boss_extra = 4.0
        boss_L = boss_len + boss_extra
        # Place so that ~2mm is inside the tank beyond the detected surface center
        inset = 2.5
        boss_center = vsub(target_center, vmul(outdir, (inset - boss_extra/2.0)))
        boss_base = vsub(boss_center, vmul(outdir, boss_L/2.0))
        boss = cq.Solid.makeCylinder(outer_r, boss_L,
                                    cq.Vector(boss_base.x, boss_base.y, boss_base.z),
                                    cq.Vector(outdir.x, outdir.y, outdir.z))

        # Cut a hole from the outer end inward
        outer_end = vadd(boss_center, vmul(outdir, boss_L/2.0))
        hole_L = boss_L + 18.0
        hole_start = vadd(outer_end, vmul(outdir, 1.0))
        hole_dir = vmul(outdir, -1)
        hole = cq.Solid.makeCylinder(inner_r, hole_L,
                                     cq.Vector(hole_start.x, hole_start.y, hole_start.z),
                                     cq.Vector(hole_dir.x, hole_dir.y, hole_dir.z))
        # Use a probe point slightly inside the tank for solid selection
        probe_point = vsub(target_center, vmul(outdir, 2.0))
        return boss, hole, probe_point

    def pick_target_solid(solids_list, probe_point: cq.Vector):
        # Pick the solid that actually occupies a small sphere around probe_point
        probe = cq.Solid.makeSphere(2.2, cq.Vector(probe_point.x, probe_point.y, probe_point.z))
        best_i = None
        best_vol = 0.0
        for i, s in enumerate(solids_list):
            try:
                sb = s.BoundingBox()
                if not (sb.xmin-3 <= probe_point.x <= sb.xmax+3 and sb.ymin-3 <= probe_point.y <= sb.ymax+3 and sb.zmin-3 <= probe_point.z <= sb.zmax+3):
                    continue
                inter = s.intersect(probe)
                vol = 0.0
                try:
                    vol = float(inter.Volume())
                except Exception:
                    try:
                        vol = float(inter.val().Volume())
                    except Exception:
                        vol = 0.0
                if vol > best_vol + 1e-6:
                    best_vol = vol
                    best_i = i
            except Exception:
                continue
        return best_i, best_vol

    def apply_port(solids_list, src, tgt_center, label: str):
        if src is None:
            print(f"ERROR: No source reference for {label}; skipping.")
            return solids_list, False

        outer_r = float(src["r"])
        inner_r = find_inner_radius(src)
        if inner_r is None:
            inner_r = max(2.5, outer_r * 0.60)
        boss_len = float(src["len"]) if src["len"] and src["len"] > 2.0 else 26.0

        outdir = choose_outdir_from_src(src["center"], src["dir"])

        boss, hole, probe_pt = make_boss_and_hole(tgt_center, outdir, outer_r, inner_r, boss_len)
        si, vol = pick_target_solid(solids_list, probe_pt)

        print(f"=== {label} ===")
        sc = src["center"]
        print(f"Source center=({sc.x:.2f},{sc.y:.2f},{sc.z:.2f}) OD={outer_r:.2f} ID={inner_r:.2f} len~{boss_len:.2f}")
        print(f"Target center=({tgt_center.x:.2f},{tgt_center.y:.2f},{tgt_center.z:.2f}) outdir=({outdir.x:.0f},{outdir.y:.0f},{outdir.z:.0f})")
        print(f"Target solid idx={si} probe_intersection_vol={vol:.3f}")

        if si is None or vol <= 1e-5:
            print(f"ERROR: Could not localize target solid for {label} (boss would float / wrong cut). Skipping.")
            return solids_list, False

        try:
            modified = cq.Workplane(obj=solids_list[si]).union(boss).cut(hole).val()
        except Exception as e:
            print(f"ERROR: Boolean failed for {label}:", e)
            return solids_list, False

        solids_list2 = list(solids_list)
        solids_list2[si] = modified
        return solids_list2, True

    ok_out = False
    ok_in = False

    # Outlet: mirror existing TOP-LEFT port to TOP-RIGHT (mirror in Y about midY)
    if src_top_left is not None:
        c = src_top_left["center"]
        tgt_out = cq.Vector(c.x, 2.0*midY - c.y, c.z)
        solids, ok_out = apply_port(solids, src_top_left, tgt_out, "Outlet port (top-right)")

    # Inlet: mirror existing BOTTOM-RIGHT port to BOTTOM-LEFT
    if src_bot_right is not None:
        c = src_bot_right["center"]
        tgt_in = cq.Vector(c.x, 2.0*midY - c.y, c.z)
        solids, ok_in = apply_port(solids, src_bot_right, tgt_in, "Inlet port (bottom-left)")

    if not ok_out or not ok_in:
        print(f"WARNING: Ports created? outlet={ok_out} inlet={ok_in}")

    result = cq.Compound.makeCompound(solids)
    try:
        print("=== Done ===")
        print("Result valid:", result.isValid())
        print("Result solids:", len(result.Solids()))
    except Exception:
        pass

    return cq.Workplane().add(result)
