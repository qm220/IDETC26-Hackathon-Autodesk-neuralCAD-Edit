def my_cad_function(args):
    import cadquery as cq
    import os
    
    input_file = os.path.expanduser(args.get("input_file", ""))
    if not input_file or not os.path.exists(input_file):
        raise ValueError(f"Missing/invalid args['input_file']: {input_file}")

    imp = cq.importers.importStep(input_file)
    base_shape = imp.val() if hasattr(imp, "val") else imp
    wp_base = cq.Workplane("XY").newObject([base_shape])

    bb = base_shape.BoundingBox()
    ymin, ymax = bb.ymin, bb.ymax
    thickness = ymax - ymin
    print(f"Loaded STEP. BBox: xmin={bb.xmin:.4f} xmax={bb.xmax:.4f} ymin={ymin:.4f} ymax={ymax:.4f} zmin={bb.zmin:.4f} zmax={bb.zmax:.4f}  thicknessY={thickness:.4f}")

    # --- Find the existing TOP pocket floor face (planar, +Y normal, near ymax-1) ---
    target_y = ymax - 1.0
    tol_y = 0.35

    def _face_area(f):
        try:
            return f.Area()
        except Exception:
            return 0.0

    pocket_candidates = []
    for f in base_shape.Faces():
        try:
            if hasattr(f, "geomType") and f.geomType() != "PLANE":
                continue
            n = f.normalAt()
            c = f.Center()
            if abs(n.y - 1.0) < 1e-3 and abs(c.y - target_y) < tol_y:
                pocket_candidates.append((f, _face_area(f), c.y))
        except Exception:
            continue

    if not pocket_candidates:
        # Relax tolerance and try again
        tol_y = 1.5
        for f in base_shape.Faces():
            try:
                if hasattr(f, "geomType") and f.geomType() != "PLANE":
                    continue
                n = f.normalAt()
                c = f.Center()
                if abs(n.y - 1.0) < 1e-3 and abs(c.y - target_y) < tol_y:
                    pocket_candidates.append((f, _face_area(f), c.y))
            except Exception:
                continue

    if not pocket_candidates:
        raise RuntimeError("Could not locate the top pocket floor face near y=ymax-1.")

    pocket_face = sorted(pocket_candidates, key=lambda t: t[1], reverse=True)[0][0]
    y_pocket = pocket_face.Center().y
    print(f"Pocket floor face found at y={y_pocket:.4f} (expected ~{target_y:.4f})")

    # --- Extract pocket footprint extents from outer wire of pocket floor ---
    ow = pocket_face.outerWire()
    verts = ow.Vertices()
    pts = [v.Center() for v in verts]
    xs = [p.x for p in pts]
    zs = [p.z for p in pts]
    x_min, x_max = min(xs), max(xs)
    z_min, z_max = min(zs), max(zs)
    x_len = x_max - x_min
    z_len = z_max - z_min
    x_c = (x_min + x_max) / 2.0
    z_c = (z_min + z_max) / 2.0

    # Estimate corner fillet radius from circular edges on the wire (fallback to 1mm)
    r_fillet = 1.0
    try:
        radii = []
        for e in ow.Edges():
            try:
                if hasattr(e, "geomType") and e.geomType() == "CIRCLE":
                    radii.append(float(e.radius()))
            except Exception:
                pass
        if radii:
            r_fillet = sum(radii) / len(radii)
    except Exception:
        pass

    print(f"Pocket footprint extents: x[{x_min:.4f},{x_max:.4f}] (len={x_len:.4f})  z[{z_min:.4f},{z_max:.4f}] (len={z_len:.4f})  center=({x_c:.4f},{z_c:.4f})  fillet~{r_fillet:.4f}")

    # --- 1) Add mirrored bottom lowered plateau (bottom pocket) ---
    plateau_depth = 1.0
    bottom_plane = cq.Plane(origin=(0, ymin, 0), xDir=(1, 0, 0), normal=(0, 1, 0))

    bottom_pocket_tool = (
        cq.Workplane(bottom_plane)
        .center(x_c, z_c)
        .rect(x_len, z_len)
        .vertices()
        .fillet(r_fillet)
        .extrude(plateau_depth)
    )

    wp_mod = wp_base.cut(bottom_pocket_tool)

    # --- 2) Add embossed text "TOP" on the top pocket floor, 1mm high (flush to top face) ---
    emboss_h = 1.0
    text_plane = cq.Plane(origin=(0, y_pocket, 0), xDir=(1, 0, 0), normal=(0, 1, 0))

    # Rotate within the XZ plane so the 10mm text height runs across X (fits pocket width)
    wp_text = (
        cq.Workplane(text_plane)
        .center(x_c, z_c)
        .transformed(rotate=(0, 90, 0))
    )

    # Create text as separate solid then union
    try:
        text_solid = wp_text.text(
            "TOP",
            fontsize=10.0,
            distance=emboss_h,
            cut=False,
            combine=False,
            font="Arial",
            halign="center",
            valign="center",
        )
    except Exception as e:
        print(f"Arial font not available or text creation failed with Arial ({e}); falling back to default font.")
        text_solid = wp_text.text(
            "TOP",
            fontsize=10.0,
            distance=emboss_h,
            cut=False,
            combine=False,
            halign="center",
            valign="center",
        )

    wp_mod = wp_mod.union(text_solid)

    # Quick sanity: report final bbox Y extents
    final_shape = wp_mod.val()
    fbb = final_shape.BoundingBox()
    print(f"Final BBox Y: ymin={fbb.ymin:.4f} ymax={fbb.ymax:.4f}")

    return wp_mod
