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
    try:
        print('Solids:', len(shp.Solids()))
    except Exception:
        pass
    bb = shp.BoundingBox()
    print(f"BBOX x:[{bb.xmin:.3f},{bb.xmax:.3f}] y:[{bb.ymin:.3f},{bb.ymax:.3f}] z:[{bb.zmin:.3f},{bb.zmax:.3f}]")
    print(f"Center: ({bb.center.x:.3f}, {bb.center.y:.3f}, {bb.center.z:.3f})")

    # ----------------------
    # Find large end faces at +/-Y (end tanks), rather than using global yMin/yMax
    # (global extremes are affected by small brackets; previous iteration placed bosses off-body)
    # ----------------------
    YAX = cq.Vector(0, 1, 0)

    def _unit(v: cq.Vector):
        L = math.sqrt(v.x*v.x + v.y*v.y + v.z*v.z)
        if L < 1e-9:
            return cq.Vector(0, 0, 0)
        return cq.Vector(v.x/L, v.y/L, v.z/L)

    def _dot(a: cq.Vector, b: cq.Vector):
        return a.x*b.x + a.y*b.y + a.z*b.z

    # Collect planar faces whose normals are ~parallel to Y
    faces_y = []
    try:
        from OCP.GeomAbs import GeomAbs_Plane
        for f in shp.Faces():
            try:
                ad = f._geomAdaptor()
                if ad.GetType() != GeomAbs_Plane:
                    continue
                pln = ad.Plane()
                d = pln.Axis().Direction()
                n = _unit(cq.Vector(d.X(), d.Y(), d.Z()))
                if abs(_dot(n, YAX)) < 0.985:
                    continue
                c = f.Center()
                a = float(f.Area())
                fb = f.BoundingBox()
                faces_y.append((f, n, c, a, fb))
            except Exception:
                continue
    except Exception as e:
        print('WARNING: Could not scan planar faces (OCP missing?):', e)

    if not faces_y:
        # Fallback: use bbox extremes (less reliable)
        print('WARNING: No suitable end faces found; falling back to global bbox yMin/yMax (may float).')
        y_pos = bb.ymax
        y_neg = bb.ymin
        # Use conservative z placement within global bbox
        z_span = bb.zmax - bb.zmin
        mz = max(18.0, min(35.0, 0.08*z_span))
        z_top = bb.zmax - mz
        z_bot = bb.zmin + mz
        x_pos = bb.center.x
        x_neg = bb.center.x
    else:
        # Split into +Y side (right end) and -Y side (left end) by face center.y
        pos = [t for t in faces_y if t[2].y >= bb.center.y]
        neg = [t for t in faces_y if t[2].y < bb.center.y]

        def pick_end_face(cands, side_name: str):
            # pick the farthest in Y, but prefer large-area faces within 15mm of the farthest
            if not cands:
                return None
            ys = [t[2].y for t in cands]
            y_ext = max(ys) if side_name == '+Y' else min(ys)
            band = 15.0
            if side_name == '+Y':
                near = [t for t in cands if t[2].y > (y_ext - band)]
            else:
                near = [t for t in cands if t[2].y < (y_ext + band)]
            # prefer largest area among near candidates
            near.sort(key=lambda t: t[3], reverse=True)
            return near[0]

        pos_pick = pick_end_face(pos, '+Y')
        neg_pick = pick_end_face(neg, '-Y')

        if pos_pick is None or neg_pick is None:
            print('WARNING: Could not reliably pick both ends; falling back to bbox.')
            y_pos = bb.ymax
            y_neg = bb.ymin
            z_span = bb.zmax - bb.zmin
            mz = max(18.0, min(35.0, 0.08*z_span))
            z_top = bb.zmax - mz
            z_bot = bb.zmin + mz
            x_pos = bb.center.x
            x_neg = bb.center.x
        else:
            f_pos, n_pos, c_pos, a_pos, fb_pos = pos_pick
            f_neg, n_neg, c_neg, a_neg, fb_neg = neg_pick

            # Use face-constant Y coordinate (center.y is fine for planar face)
            y_pos = c_pos.y
            y_neg = c_neg.y

            # Place ports within the picked end-face z extents (avoid filler-neck extremes elsewhere)
            zspan_pos = fb_pos.zmax - fb_pos.zmin
            zspan_neg = fb_neg.zmax - fb_neg.zmin
            mz_pos = max(18.0, min(35.0, 0.08*zspan_pos))
            mz_neg = max(18.0, min(35.0, 0.08*zspan_neg))
            z_top = fb_pos.zmax - mz_pos
            z_bot = fb_neg.zmin + mz_neg

            # Center in X within that end face
            x_pos = 0.5*(fb_pos.xmin + fb_pos.xmax)
            x_neg = 0.5*(fb_neg.xmin + fb_neg.xmax)

            print('=== Picked end faces ===')
            print(f"+Y end face: center=({c_pos.x:.3f},{c_pos.y:.3f},{c_pos.z:.3f}) area={a_pos:.1f} faceBB y[{fb_pos.ymin:.3f},{fb_pos.ymax:.3f}] z[{fb_pos.zmin:.3f},{fb_pos.zmax:.3f}]")
            print(f"-Y end face: center=({c_neg.x:.3f},{c_neg.y:.3f},{c_neg.z:.3f}) area={a_neg:.1f} faceBB y[{fb_neg.ymin:.3f},{fb_neg.ymax:.3f}] z[{fb_neg.zmin:.3f},{fb_neg.zmax:.3f}]")

    print('=== Target placement (interpreting right-view: +Y=right, +Z=top) ===')
    print(f"Outlet (top-right):  y={y_pos:.3f}, x={x_pos:.3f}, z={z_top:.3f}")
    print(f"Inlet  (bot-left):   y={y_neg:.3f}, x={x_neg:.3f}, z={z_bot:.3f}")

    # ----------------------
    # Port geometry (simple hose boss + through hole)
    # ----------------------
    port_od = 30.0
    port_id = 18.0
    boss_len = 26.0
    hole_depth = 80.0
    eps = 0.6  # overlap into body to guarantee fuse

    def add_port(wp, y_face, normal_dir, x_c, z_c, od, idd, bossL, holeD):
        # Sketch plane: normal along +/-Y, xDir along +X.
        # In this plane's 2D coords: u aligns with global X, v aligns with +/-Z depending on normal.
        pl_boss = cq.Plane(origin=(0, y_face - normal_dir*eps, 0), xDir=(1, 0, 0), normal=(0, normal_dir, 0))
        v_local = (-z_c) if normal_dir > 0 else (z_c)

        boss = (
            cq.Workplane(pl_boss)
            .center(x_c, v_local)
            .circle(od/2.0)
            .extrude(bossL + eps)
        )

        # Hole starts at the outer end of boss and cuts inward
        pl_hole = cq.Plane(origin=(0, y_face + normal_dir*(bossL + 0.2), 0), xDir=(1, 0, 0), normal=(0, normal_dir, 0))
        hole = (
            cq.Workplane(pl_hole)
            .center(x_c, v_local)
            .circle(idd/2.0)
            .extrude(-(holeD + 0.4))
        )

        return wp.union(boss).cut(hole)

    result = cq.Workplane().add(shp)

    # Outlet on +Y end, near top (+Z)
    result = add_port(result, y_face=y_pos, normal_dir=+1, x_c=x_pos, z_c=z_top,
                      od=port_od, idd=port_id, bossL=boss_len, holeD=hole_depth)

    # Inlet on -Y end, near bottom (-Z)
    result = add_port(result, y_face=y_neg, normal_dir=-1, x_c=x_neg, z_c=z_bot,
                      od=port_od, idd=port_id, bossL=boss_len, holeD=hole_depth)

    try:
        print('=== Done ===')
        print('Result valid:', result.val().isValid())
        print('Result solids:', len(result.val().Solids()))
    except Exception:
        pass

    return result
