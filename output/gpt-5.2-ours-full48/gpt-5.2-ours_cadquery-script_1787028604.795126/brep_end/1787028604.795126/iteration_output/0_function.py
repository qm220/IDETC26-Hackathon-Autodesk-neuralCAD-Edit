def my_cad_function(args):
    import os
    import cadquery as cq

    # OCC helpers (for robust hole-cylinder detection)
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder

    if "input_file" not in args:
        raise ValueError("Missing args['input_file'] for edit task")

    input_file = os.path.expanduser(args["input_file"])
    part_wp = cq.importers.importStep(input_file)
    part_shape = part_wp.val() if hasattr(part_wp, "val") else part_wp

    # --- Find the two base mounting through-holes (vertical axis ~Y, R~7.5, short height ~15) ---
    cyl_candidates = []
    for f in part_shape.Faces():
        try:
            ad = BRepAdaptor_Surface(f.wrapped)
            if ad.GetType() != GeomAbs_Cylinder:
                continue
            cyl = ad.Cylinder()
            r = float(cyl.Radius())
            ax = cyl.Axis()
            d = ax.Direction()
            # axis ~ Y
            if abs(float(d.Y())) < 0.95:
                continue
            bb = f.BoundingBox()
            y_len = bb.ylen
            # base holes: short cylinder height (base thickness ~15)
            if y_len > 30:
                continue
            # radius ~7.5mm (Ø~15)
            if not (7.0 <= r <= 8.2):
                continue

            loc = ax.Location()
            cyl_candidates.append({
                "face": f,
                "r": r,
                "axis_loc": (float(loc.X()), float(loc.Y()), float(loc.Z())),
                "ymin": bb.ymin,
                "ymax": bb.ymax,
                "ylen": y_len,
                "bb": bb
            })
        except Exception:
            continue

    # If more than 2 candidates, prefer those closest to base (smallest ymax)
    cyl_candidates = sorted(cyl_candidates, key=lambda c: (c["ymax"], c["r"]))

    print(f"Loaded STEP: {input_file}")
    bbp = part_shape.BoundingBox()
    print(f"Part bbox: x[{bbp.xmin:.3f},{bbp.xmax:.3f}] y[{bbp.ymin:.3f},{bbp.ymax:.3f}] z[{bbp.zmin:.3f},{bbp.zmax:.3f}]")
    print(f"Found {len(cyl_candidates)} vertical short cylinders near R~7.5")
    for i, c in enumerate(cyl_candidates[:10]):
        axx, axy, axz = c["axis_loc"]
        print(f"  cand {i}: r={c['r']:.3f}, axis_loc=({axx:.3f},{axy:.3f},{axz:.3f}), y[{c['ymin']:.3f},{c['ymax']:.3f}] len={c['ylen']:.3f}")

    # Take up to two holes
    holes = cyl_candidates[:2]
    if len(holes) < 2:
        # Fallback: do nothing but return the part for inspection
        print("WARNING: Could not reliably find both base mounting holes. Returning part only.")
        return part_wp

    # --- Build a simple screw solid (not threaded, assembly representation) ---
    # Use detected hole radius to size shank/head
    hole_r = sum(h["r"] for h in holes) / len(holes)
    shank_r = max(0.1, hole_r - 0.5)      # slight clearance to visually fit
    head_r = hole_r * 1.35                # generic head size
    head_h = 8.0
    shank_len = 60.0                      # arbitrary: long enough to go into table

    # Model: underside of head at y=0, head goes +Y, shank goes -Y
    screw = (
        cq.Workplane("XZ")
        .circle(shank_r).extrude(-shank_len)
        .union(cq.Workplane("XZ").circle(head_r).extrude(head_h))
        .faces(">Y").edges().chamfer(1.0)
    )

    # --- Place screws concentrically into the holes, heads bearing on base top (hole ymax) ---
    assy = cq.Assembly()
    assy.add(part_shape, name="bracket", color=cq.Color(0.75, 0.75, 0.75))

    for idx, h in enumerate(holes):
        x0, _, z0 = h["axis_loc"]
        y_top = h["ymax"]  # base top at that hole

        screw_i = screw.translate((x0, y_top, z0))
        assy.add(screw_i, name=f"screw_{idx+1}", color=cq.Color(0.35, 0.35, 0.38))
        print(f"Placed screw_{idx+1} at x={x0:.3f}, z={z0:.3f}, head_underside_y={y_top:.3f}")

    return assy
