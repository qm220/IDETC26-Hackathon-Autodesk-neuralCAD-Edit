def my_cad_function(args):
    import os, math
    import cadquery as cq

    input_file = os.path.expanduser(args.get('input_file', ''))
    if not input_file or (not os.path.exists(input_file)):
        raise ValueError(f"Missing or invalid args['input_file']: {input_file}")

    base = cq.importers.importStep(input_file)
    shp = base.val()

    print('=== Loaded model ===')
    try:
        print('Valid:', shp.isValid())
    except Exception:
        pass
    solids = []
    try:
        solids = shp.Solids()
        print('Solids:', len(solids))
    except Exception:
        pass
    bb = shp.BoundingBox()
    print(f"BBOX x:[{bb.xmin:.3f},{bb.xmax:.3f}] y:[{bb.ymin:.3f},{bb.ymax:.3f}] z:[{bb.zmin:.3f},{bb.zmax:.3f}]")
    print(f"Center: ({bb.center.x:.3f}, {bb.center.y:.3f}, {bb.center.z:.3f})")

    XAX = cq.Vector(1, 0, 0)

    def unit(v: cq.Vector):
        L = math.sqrt(v.x*v.x + v.y*v.y + v.z*v.z)
        if L < 1e-12:
            return cq.Vector(0, 0, 0)
        return cq.Vector(v.x/L, v.y/L, v.z/L)

    def dot(a: cq.Vector, b: cq.Vector):
        return a.x*b.x + a.y*b.y + a.z*b.z

    def vadd(a: cq.Vector, b: cq.Vector):
        return cq.Vector(a.x+b.x, a.y+b.y, a.z+b.z)

    def vsub(a: cq.Vector, b: cq.Vector):
        return cq.Vector(a.x-b.x, a.y-b.y, a.z-b.z)

    def vmul(a: cq.Vector, s: float):
        return cq.Vector(a.x*s, a.y*s, a.z*s)

    midY = bb.center.y
    midZ = bb.center.z
    yspan = max(1e-6, bb.ymax - bb.ymin)

    # --- Detect existing port-like cylinders (axis ~ X, near Y extremes) ---
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

                # focus on cylinders aligned with X (ports/fans both are, so filter further)
                if abs(dot(dirv, XAX)) < 0.965:
                    continue

                c = f.Center()
                fb = f.BoundingBox()

                # near Y extremes (avoid central fan motor cylinders)
                if abs(c.y - midY) < 0.30 * yspan:
                    continue

                # likely port sizes; avoid very large fan features
                if not (6.0 <= r <= 35.0):
                    continue

                # estimate length along X from face bbox (works since axis ~ X)
                est_len = float(fb.xmax - fb.xmin)
                cyls.append({
                    'face': f,
                    'center': cq.Vector(c.x, c.y, c.z),
                    'dir': dirv,
                    'r': r,
                    'fb': fb,
                    'len': est_len,
                })
            except Exception:
                continue
    except Exception as e:
        print('WARNING: Cylinder scan failed:', e)

    print(f"Detected X-axis, Y-extreme cylinders: {len(cyls)}")
    if len(cyls) > 0:
        # print a few candidates
        cyls_sorted = sorted(cyls, key=lambda t: (-abs(t['center'].y - midY), -t['r']))
        for i, t in enumerate(cyls_sorted[:8]):
            cc = t['center']
            print(f"  cand[{i}] c=({cc.x:.2f},{cc.y:.2f},{cc.z:.2f}) r={t['r']:.2f} len~{t['len']:.2f}")

    def pick_source(which: str):
        # which: 'top_left' or 'bot_right'
        left = [t for t in cyls if t['center'].y < midY]
        right = [t for t in cyls if t['center'].y > midY]
        if which == 'top_left':
            pref = [t for t in left if t['center'].z > midZ]
            if not pref:
                pref = left
            if not pref:
                return None
            return max(pref, key=lambda t: t['center'].z)
        if which == 'bot_right':
            pref = [t for t in right if t['center'].z < midZ]
            if not pref:
                pref = right
            if not pref:
                return None
            return min(pref, key=lambda t: t['center'].z)
        return None

    src_top_left = pick_source('top_left')
    src_bot_right = pick_source('bot_right')

    if src_top_left is None or src_bot_right is None:
        print('WARNING: Could not reliably identify existing reference ports. Falling back to simple placed bosses (may be less accurate).')

    def find_inner_radius(src):
        if src is None:
            return None
        c0 = src['center']
        d0 = src['dir']
        r0 = src['r']
        best = None
        for t in cyls:
            if t is src:
                continue
            # same axis direction (parallel to X already)
            if abs(dot(t['dir'], d0)) < 0.99:
                continue
            c = t['center']
            if abs(c.y - c0.y) > 2.5:
                continue
            if abs(c.z - c0.z) > 2.5:
                continue
            if abs(c.x - c0.x) > 4.0:
                continue
            if t['r'] >= (r0 - 0.8):
                continue
            if best is None or t['r'] < best:
                best = t['r']
        return best

    def already_has_port_at(target_center, r, tol_yz=3.5, tol_r=1.5):
        for t in cyls:
            c = t['center']
            if abs(c.y - target_center.y) < tol_yz and abs(c.z - target_center.z) < tol_yz:
                if abs(t['r'] - r) < tol_r:
                    return True
        return False

    def make_port_solids(center: cq.Vector, axis_dir: cq.Vector, outer_r: float, inner_r: float, boss_len: float, wall_pen: float):
        axis_dir = unit(axis_dir)

        # Determine outward direction based on model center (port should protrude away from bulk)
        to_c = vsub(center, cq.Vector(bb.center.x, bb.center.y, bb.center.z))
        outdir = axis_dir if dot(axis_dir, to_c) > 0 else vmul(axis_dir, -1)

        # Make boss cylinder centered at 'center'
        bossH = max(10.0, min(80.0, boss_len))
        overlap = 1.0
        bossH2 = bossH + overlap
        boss_base = vsub(center, vmul(outdir, bossH2/2.0))
        boss = cq.Solid.makeCylinder(outer_r, bossH2, cq.Vector(boss_base.x, boss_base.y, boss_base.z), cq.Vector(outdir.x, outdir.y, outdir.z))

        # Make hole starting slightly outside outer end and cutting inward across boss + wall penetration
        outer_end = vadd(center, vmul(outdir, bossH/2.0))
        holeH = bossH + max(4.0, wall_pen) + 2.0
        hole_start = vadd(outer_end, vmul(outdir, 0.8))
        hole_dir = vmul(outdir, -1)
        hole = cq.Solid.makeCylinder(inner_r, holeH, cq.Vector(hole_start.x, hole_start.y, hole_start.z), cq.Vector(hole_dir.x, hole_dir.y, hole_dir.z))

        return boss, hole

    result = cq.Workplane().add(shp)

    # --- Create outlet port (top-right) by mirroring an existing top-left port across Y mid-plane ---
    if src_top_left is not None:
        c = src_top_left['center']
        outer_r = float(src_top_left['r'])
        inner_r = find_inner_radius(src_top_left)
        if inner_r is None:
            inner_r = max(2.5, outer_r * 0.60)

        boss_len = float(src_top_left['len'])
        if boss_len < 8.0:
            boss_len = 26.0

        tgt = cq.Vector(c.x, 2.0*midY - c.y, c.z)  # mirror to right

        print('=== Outlet port target (top-right) ===')
        print(f"Source top-left center=({c.x:.2f},{c.y:.2f},{c.z:.2f}) rOD={outer_r:.2f} rID={inner_r:.2f} len~{boss_len:.2f}")
        print(f"Mirrored target center=({tgt.x:.2f},{tgt.y:.2f},{tgt.z:.2f})")

        if not already_has_port_at(tgt, outer_r):
            boss, hole = make_port_solids(
                center=tgt,
                axis_dir=src_top_left['dir'],
                outer_r=outer_r,
                inner_r=inner_r,
                boss_len=boss_len,
                wall_pen=10.0
            )
            result = result.union(boss).cut(hole)
        else:
            print('Outlet port seems to already exist at mirrored location; skipping creation.')
    else:
        # fallback: place a generic port near top-right corner using bbox (axis along X)
        print('Outlet fallback placement used.')
        tgt = cq.Vector(bb.center.x, bb.ymax - 10.0, bb.zmax - 20.0)
        boss, hole = make_port_solids(tgt, cq.Vector(1, 0, 0), 15.0, 9.0, 26.0, 10.0)
        result = result.union(boss).cut(hole)

    # --- Create inlet port (bottom-left) by mirroring an existing bottom-right port across Y mid-plane ---
    if src_bot_right is not None:
        c = src_bot_right['center']
        outer_r = float(src_bot_right['r'])
        inner_r = find_inner_radius(src_bot_right)
        if inner_r is None:
            inner_r = max(2.5, outer_r * 0.60)

        boss_len = float(src_bot_right['len'])
        if boss_len < 8.0:
            boss_len = 26.0

        tgt = cq.Vector(c.x, 2.0*midY - c.y, c.z)  # mirror to left

        print('=== Inlet port target (bottom-left) ===')
        print(f"Source bottom-right center=({c.x:.2f},{c.y:.2f},{c.z:.2f}) rOD={outer_r:.2f} rID={inner_r:.2f} len~{boss_len:.2f}")
        print(f"Mirrored target center=({tgt.x:.2f},{tgt.y:.2f},{tgt.z:.2f})")

        if not already_has_port_at(tgt, outer_r):
            boss, hole = make_port_solids(
                center=tgt,
                axis_dir=src_bot_right['dir'],
                outer_r=outer_r,
                inner_r=inner_r,
                boss_len=boss_len,
                wall_pen=10.0
            )
            result = result.union(boss).cut(hole)
        else:
            print('Inlet port seems to already exist at mirrored location; skipping creation.')
    else:
        # fallback: place a generic port near bottom-left corner using bbox (axis along X)
        print('Inlet fallback placement used.')
        tgt = cq.Vector(bb.center.x, bb.ymin + 10.0, bb.zmin + 20.0)
        boss, hole = make_port_solids(tgt, cq.Vector(1, 0, 0), 15.0, 9.0, 26.0, 10.0)
        result = result.union(boss).cut(hole)

    try:
        out = result.val()
        print('=== Done ===')
        try:
            print('Result valid:', out.isValid())
        except Exception:
            pass
        try:
            print('Result solids:', len(out.Solids()))
        except Exception:
            pass
    except Exception as e:
        print('WARNING: Could not evaluate result:', e)

    return result
