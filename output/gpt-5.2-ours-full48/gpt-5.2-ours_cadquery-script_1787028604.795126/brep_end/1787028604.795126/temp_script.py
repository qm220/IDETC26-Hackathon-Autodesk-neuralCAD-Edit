def my_cad_function(args):
    import os
    import cadquery as cq

    # OCC helpers for robust hole-cylinder detection
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

    # --- Find the two base mounting through-holes (vertical axis ~Y, R~7.5, in base y~0..15) ---
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
            if abs(float(d.Y())) < 0.97:
                continue

            # radius ~7.5mm (Ø~15)
            if not (7.0 <= r <= 8.2):
                continue

            bb = f.BoundingBox()
            ylen = bb.ylen

            # base holes are short and start at the bottom
            if ylen > 25.0:
                continue
            if bb.ymin > (bbp.ymin + 0.5):
                continue
            if bb.ymax > (bbp.ymin + 35.0):
                continue

            loc = ax.Location()
            cyl_candidates.append({
                "face": f,
                "r": r,
                "axis_loc": (float(loc.X()), float(loc.Y()), float(loc.Z())),
                "ymin": bb.ymin,
                "ymax": bb.ymax,
                "ylen": ylen,
            })
        except Exception:
            continue

    cyl_candidates = sorted(
        cyl_candidates,
        key=lambda c: (abs(c["ymax"] - (bbp.ymin + 15.0)), c["axis_loc"][0])
    )

    print(f"Found {len(cyl_candidates)} candidate base-hole cylinders")
    for i, c in enumerate(cyl_candidates[:10]):
        x, y, z = c["axis_loc"]
        print(f"  cand {i}: r={c['r']:.3f}, axis_loc=({x:.3f},{y:.3f},{z:.3f}), y[{c['ymin']:.3f},{c['ymax']:.3f}] len={c['ylen']:.3f}")

    holes = cyl_candidates[:2]
    if len(holes) < 2:
        print("WARNING: Could not reliably find both base mounting holes. Returning part only.")
        return part_wp

    # --- Build a simple screw + washer (non-threaded representation), axis along Y ---
    hole_r = sum(h["r"] for h in holes) / len(holes)  # ~7.5

    shank_r = max(0.1, hole_r - 0.6)   # small clearance so it visually fits
    head_r = hole_r * 1.45
    head_h = 9.0
    washer_r = head_r * 1.05
    washer_h = 1.6

    # show some length below the base to indicate it goes into the table/nut
    shank_len = max(45.0, min(70.0, bbp.ylen * 0.35))

    # Local coordinate convention:
    #   washer underside is at y=0 (bearing on base top)
    #   shank extends toward -Y
    shank = cq.Solid.makeCylinder(shank_r, shank_len, cq.Vector(0, 0, 0), cq.Vector(0, -1, 0))

    washer = cq.Solid.makeCylinder(washer_r, washer_h, cq.Vector(0, 0, 0), cq.Vector(0, 1, 0))
    washer_hole = cq.Solid.makeCylinder(shank_r * 1.05, washer_h + 0.5, cq.Vector(0, 0, 0), cq.Vector(0, 1, 0))
    washer = washer.cut(washer_hole)

    head = cq.Solid.makeCylinder(head_r, head_h, cq.Vector(0, washer_h, 0), cq.Vector(0, 1, 0))

    # Keep as a Compound (no combineSolids call; that caused the previous crash)
    fastener = cq.Compound.makeCompound([shank, washer, head])
    fastener_wp = cq.Workplane(obj=fastener)

    bbf = fastener_wp.val().BoundingBox()
    print(f"Fastener bbox (local): y[{bbf.ymin:.3f},{bbf.ymax:.3f}] (expect ymin<0, ymax>0)")

    # --- Place screws concentrically into the two holes, washer underside at base top (hole ymax) ---
    assy = cq.Assembly()
    assy.add(part_shape, name="bracket", color=cq.Color(0.75, 0.75, 0.75))

    holes_sorted = sorted(holes, key=lambda c: c["axis_loc"][0])
    for idx, h in enumerate(holes_sorted):
        x0, _, z0 = h["axis_loc"]
        y_top = h["ymax"]  # expected ~15

        inst = fastener_wp.translate((x0, y_top, z0))
        assy.add(inst, name=f"screw_{idx+1}", color=cq.Color(0.35, 0.35, 0.38))

        bb_inst = inst.val().BoundingBox()
        print(
            f"Placed screw_{idx+1}: axis at x={x0:.3f}, z={z0:.3f}; washer_underside_y={y_top:.3f}; "
            f"instance y[{bb_inst.ymin:.3f},{bb_inst.ymax:.3f}]"
        )

    return assy
