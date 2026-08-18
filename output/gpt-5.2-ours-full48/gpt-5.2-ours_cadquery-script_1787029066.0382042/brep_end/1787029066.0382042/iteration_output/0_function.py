def my_cad_function(args):
    import os
    import math
    import cadquery as cq

    input_file = os.path.expanduser(args.get("input_file", ""))
    if not input_file or (not os.path.exists(input_file)):
        raise ValueError(f"Missing or invalid args['input_file']: {input_file}")

    base = cq.importers.importStep(input_file)
    shp = base.val() if hasattr(base, "val") else base

    bbox = shp.BoundingBox()
    xMin, xMax = bbox.xmin, bbox.xmax
    yMin, yMax = bbox.ymin, bbox.ymax
    zMin, zMax = bbox.zmin, bbox.zmax
    c = bbox.center

    print("=== Loaded model ===")
    print(f"Valid: {shp.isValid()}")
    try:
        solids = shp.Solids()
        print(f"Solids: {len(solids)}")
    except Exception:
        pass
    print(f"BBOX x:[{xMin:.3f},{xMax:.3f}] y:[{yMin:.3f},{yMax:.3f}] z:[{zMin:.3f},{zMax:.3f}]")
    print(f"Center: ({c.x:.3f}, {c.y:.3f}, {c.z:.3f})")

    # --- Try to infer existing end-port diameters from cylindrical faces whose axes are ~parallel to Y ---
    port_od = 30.0
    port_id = 18.0
    boss_len = 26.0
    hole_depth = 70.0

    def _vec_dot(a, b):
        return a.x * b.x + a.y * b.y + a.z * b.z

    def _vec_len(a):
        return math.sqrt(a.x * a.x + a.y * a.y + a.z * a.z)

    def _unit(v):
        L = _vec_len(v)
        if L < 1e-9:
            return v
        return cq.Vector(v.x / L, v.y / L, v.z / L)

    cyl_radii = []
    try:
        from OCP.GeomAbs import GeomAbs_Cylinder
        for f in shp.Faces():
            try:
                ad = f._geomAdaptor()
                if ad.GetType() != GeomAbs_Cylinder:
                    continue
                cyl = ad.Cylinder()
                r = float(cyl.Radius())
                ax = cyl.Axis().Direction()
                axv = _unit(cq.Vector(ax.X(), ax.Y(), ax.Z()))
                # axis parallel to +/-Y
                if abs(_vec_dot(axv, cq.Vector(0, 1, 0))) < 0.95:
                    continue
                # near either end in Y
                fc = f.Center()
                if min(abs(fc.y - yMax), abs(fc.y - yMin)) > 8.0:
                    continue
                if 4.0 < r < 80.0:
                    cyl_radii.append(r)
            except Exception:
                continue

        if cyl_radii:
            cyl_radii_sorted = sorted(cyl_radii)
            # pick a "large" radius as OD and a "small" as ID if available
            r_small = cyl_radii_sorted[0]
            r_large = cyl_radii_sorted[-1]
            # sanity: require some separation
            if r_large > r_small * 1.15:
                port_od = max(20.0, min(90.0, 2.0 * r_large))
                port_id = max(8.0, min(port_od - 4.0, 2.0 * r_small))
            else:
                # only one obvious size; use it as OD and derive ID
                port_od = max(20.0, min(90.0, 2.0 * r_large))
                port_id = max(8.0, min(port_od - 6.0, 0.65 * port_od))

        print("=== Port size inference ===")
        print(f"Candidate end-cylinder radii count: {len(cyl_radii)}")
        if cyl_radii:
            print(f"Radii sample (sorted, up to 12): {sorted(cyl_radii)[:12]}")
        print(f"Using port OD={port_od:.2f} mm, ID={port_id:.2f} mm, boss_len={boss_len:.2f} mm")
    except Exception as e:
        print("Port size inference skipped (missing OCP/GeomAbs access or other error):", e)
        print(f"Using default port OD={port_od:.2f} mm, ID={port_id:.2f} mm")

    # --- Placement strategy ---
    # Interpreting: "top right" = +Y end, near +Z (top). "bottom left" = -Y end, near -Z (bottom).
    # Ports protrude normal to the end faces (along +/-Y).
    diag = math.sqrt((xMax - xMin) ** 2 + (yMax - yMin) ** 2 + (zMax - zMin) ** 2)
    edge_offset = max(14.0, min(28.0, 0.06 * diag))

    x_target = c.x
    z_top = zMax - edge_offset
    z_bot = zMin + edge_offset

    print("=== Placement ===")
    print(f"edge_offset={edge_offset:.2f} mm")
    print(f"Outlet target (top-right): y={yMax:.3f}, z={z_top:.3f}, x={x_target:.3f}")
    print(f"Inlet target  (bot-left): y={yMin:.3f}, z={z_bot:.3f}, x={x_target:.3f}")

    def make_boss_and_hole(y_plane, normal_dir, x_c, z_c, od, idd, bossL, holeD):
        # Define a plane with normal along +/-Y and xDir along +X.
        # Local coordinates: u along +X; v along yDir where yDir = normal x xDir.
        # For normal=+Y => v along -Z; for normal=-Y => v along +Z.
        pl = cq.Plane(origin=(0, y_plane, 0), xDir=(1, 0, 0), normal=(0, normal_dir, 0))
        v_local = (-z_c) if normal_dir > 0 else (z_c)

        boss = (
            cq.Workplane(pl)
            .center(x_c, v_local)
            .circle(od / 2.0)
            .extrude(bossL)
        )

        pl_outer = cq.Plane(origin=(0, y_plane + normal_dir * bossL, 0), xDir=(1, 0, 0), normal=(0, normal_dir, 0))
        hole = (
            cq.Workplane(pl_outer)
            .center(x_c, v_local)
            .circle(idd / 2.0)
            .extrude(-holeD)
        )
        return boss, hole

    outlet_boss, outlet_hole = make_boss_and_hole(
        y_plane=yMax,
        normal_dir=+1,
        x_c=x_target,
        z_c=z_top,
        od=port_od,
        idd=port_id,
        bossL=boss_len,
        holeD=hole_depth,
    )

    inlet_boss, inlet_hole = make_boss_and_hole(
        y_plane=yMin,
        normal_dir=-1,
        x_c=x_target,
        z_c=z_bot,
        od=port_od,
        idd=port_id,
        bossL=boss_len,
        holeD=hole_depth,
    )

    # Boolean ops
    result = base.union(outlet_boss).union(inlet_boss)
    result = result.cut(outlet_hole).cut(inlet_hole)

    print("=== Done ===")
    try:
        print(f"Result valid: {result.val().isValid()}")
    except Exception:
        pass

    return result
