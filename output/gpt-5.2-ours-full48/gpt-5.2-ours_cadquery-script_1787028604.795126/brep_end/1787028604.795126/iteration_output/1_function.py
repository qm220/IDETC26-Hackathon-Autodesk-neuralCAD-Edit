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

    bbp = part_shape.BoundingBox()
    print(f"Loaded STEP: {input_file}")
    print(f"Part bbox: x[{bbp.xmin:.3f},{bbp.xmax:.3f}] y[{bbp.ymin:.3f},{bbp.ymax:.3f}] z[{bbp.zmin:.3f},{bbp.zmax:.3f}]")

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
            })
        except Exception:
            continue

    cyl_candidates = sorted(cyl_candidates, key=lambda c: (c["ymax"], c["r"]))

    print(f"Found {len(cyl_candidates)} vertical short cylinders near R~7.5")
    for i, c in enumerate(cyl_candidates[:10]):
        x, y, z = c["axis_loc"]
        print(f"  cand {i}: r={c['r']:.3f}, axis_loc=({x:.3f},{y:.3f},{z:.3f}), y[{c['ymin']:.3f},{c['ymax']:.3f}] len={c['ylen']:.3f}")

    holes = cyl_candidates[:2]
    if len(holes) < 2:
        print("WARNING: Could not reliably find both base mounting holes. Returning part only.")
        return part_wp

    # --- Build a simple screw + washer (non-threaded representation) ---
    hole_r = sum(h["r"] for h in holes) / len(holes)  # ~7.5

    # Visual-fit shank slightly smaller than hole
    shank_r = max(0.1, hole_r - 0.6)
    shank_len = max(60.0, (bbp.ylen * 0.6))

    # Generic socket-head proportions
    head_r = hole_r * 1.45
    head_h = 9.0

    washer_r = head_r * 1.05
    washer_h = 1.6

    # Model with head underside at y=0; head goes +Y, shank goes -Y
    screw = (
        cq.Workplane("XZ")
        .circle(shank_r).extrude(-shank_len)
        .union(cq.Workplane("XZ").circle(head_r).extrude(head_h))
    )

    # Add a simple washer under head (goes slightly +Y so underside still at y=0)
    washer = (
        cq.Workplane("XZ")
        .circle(washer_r).extrude(washer_h)
        .cut(cq.Workplane("XZ").circle(shank_r * 1.02).extrude(washer_h + 0.2))
    )

    # Small top chamfer to make it look less like a plain cylinder
    screw = screw.faces(">Y").edges().chamfer(1.0)

    fastener = screw.union(washer)

    # --- Place screws concentrically into the holes, heads bearing on base top (hole ymax) ---
    assy = cq.Assembly()
    assy.add(part_shape, name="bracket", color=cq.Color(0.75, 0.75, 0.75))

    for idx, h in enumerate(holes):
        x0, _, z0 = h["axis_loc"]
        y_top = h["ymax"]  # base top at that hole (expected ~15)

        # Translate so head underside (and washer underside) sits on base top
        inst = fastener.translate((x0, y_top, z0))
        assy.add(inst, name=f"screw_{idx+1}", color=cq.Color(0.35, 0.35, 0.38))
        print(f"Placed screw_{idx+1} at x={x0:.3f}, z={z0:.3f}, head_underside_y={y_top:.3f}, shank_len={shank_len:.1f}")

    return assy
