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
    print(
        f"Loaded STEP. BBox: x[{bb.xmin:.4f},{bb.xmax:.4f}] y[{ymin:.4f},{ymax:.4f}] z[{bb.zmin:.4f},{bb.zmax:.4f}]"
    )

    # ------------------------
    # Helper: stable workplane on a Y=const plane.
    # NOTE: With normal +Y and xDir +X, the plane's local +Y axis points toward global -Z.
    # So Workplane.center(x, y_local) maps to global (x, z) = (x, -y_local).
    # We'll always use center(x, -z) to target a global (x, z).
    def _wp_on_y(yval):
        pl = cq.Plane(origin=(0, yval, 0), xDir=(1, 0, 0), normal=(0, 1, 0))
        return cq.Workplane(pl)

    def _area(f):
        try:
            return float(f.Area())
        except Exception:
            return 0.0

    # ------------------------
    # Find existing TOP pocket floor face: planar, normal +Y, near ymax-1
    target_y = ymax - 1.0
    tol_y = 0.35

    pocket_candidates = []
    for f in base_shape.Faces():
        try:
            if hasattr(f, "geomType") and f.geomType() != "PLANE":
                continue
            n = f.normalAt()
            c = f.Center()
            if abs(n.y - 1.0) < 1e-3 and abs(c.y - target_y) < tol_y:
                pocket_candidates.append((f, _area(f)))
        except Exception:
            pass

    if not pocket_candidates:
        tol_y = 1.5
        for f in base_shape.Faces():
            try:
                if hasattr(f, "geomType") and f.geomType() != "PLANE":
                    continue
                n = f.normalAt()
                c = f.Center()
                if abs(n.y - 1.0) < 1e-3 and abs(c.y - target_y) < tol_y:
                    pocket_candidates.append((f, _area(f)))
            except Exception:
                pass

    if not pocket_candidates:
        raise RuntimeError("Could not locate the top recessed pocket floor face near y=ymax-1.")

    pocket_face = sorted(pocket_candidates, key=lambda t: t[1], reverse=True)[0][0]
    y_pocket = pocket_face.Center().y
    print(f"Pocket floor located at y={y_pocket:.4f} (expected ~{target_y:.4f})")

    # Extract pocket footprint extents from the outer wire of the pocket floor
    ow = pocket_face.outerWire()
    pts = [v.Center() for v in ow.Vertices()]
    xs = [p.x for p in pts]
    zs = [p.z for p in pts]
    x_min, x_max = min(xs), max(xs)
    z_min, z_max = min(zs), max(zs)
    x_len, z_len = (x_max - x_min), (z_max - z_min)
    x_c, z_c = (x_min + x_max) / 2.0, (z_min + z_max) / 2.0

    # Estimate corner fillet radius from circular edges on the outer wire; fallback to 1
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

    r_fillet = max(0.0, min(r_fillet, 0.49 * min(x_len, z_len)))
    print(
        f"Pocket footprint: x[{x_min:.4f},{x_max:.4f}] len={x_len:.4f}; z[{z_min:.4f},{z_max:.4f}] len={z_len:.4f}; center=({x_c:.4f},{z_c:.4f}); fillet~{r_fillet:.4f}"
    )

    # ------------------------
    # 1) Bottom mirrored recessed plateau (cut) to enforce symmetry about mid-thickness ZX plane
    plateau_depth = 1.0

    # Prefer sketch fillet; if not available, do 3D fillet after extrude.
    bottom_wp = _wp_on_y(ymin).center(x_c, -z_c)
    bottom_tool = None
    try:
        sk = cq.Sketch().rect(x_len, z_len).fillet(r_fillet)
        bottom_tool = bottom_wp.placeSketch(sk).extrude(plateau_depth)
    except Exception as e:
        print(f"Sketch fillet path failed ({e}); falling back to 3D fillet on extruded rectangle.")
        bottom_tool = (
            bottom_wp
            .rect(x_len, z_len)
            .extrude(plateau_depth)
            .edges("|Y")
            .fillet(r_fillet)
        )

    wp_mod = wp_base.cut(bottom_tool)

    # ------------------------
    # 2) Embossed text "TOP" on top pocket floor (1mm high), contained within the pocket
    emboss_h = 1.0
    desired_fontsize = 10.0

    # In-plane rotation about +Y to run the long word direction along Z (pocket length), improving fit.
    rot_about_y = 90

    def _make_text_solid(fontsize):
        wpt = (
            _wp_on_y(y_pocket)
            .center(x_c, -z_c)
            .transformed(rotate=(0, rot_about_y, 0))
        )
        # Avoid unsupported keyword args (previous iteration failed on 'cut').
        # Try with Arial, then fallback to default font.
        try:
            return wpt.text("TOP", fontsize, emboss_h, font="Arial")
        except Exception as e1:
            print(f"Arial font or font kw not supported ({e1}); falling back to default text call.")
            return wpt.text("TOP", fontsize, emboss_h)

    # Try to ensure the produced text bbox stays inside the pocket bbox in plan view.
    # (bbox-based, conservative; text is rotated so its larger dimension is along Z.)
    margin = 0.30
    fontsize = desired_fontsize
    text_wp = _make_text_solid(fontsize)
    text_bb = text_wp.val().BoundingBox()

    def _overflow_score(tbb):
        # Only consider plan-view containment (X,Z).
        s = 0.0
        s += max(0.0, (x_min + margin) - tbb.xmin)
        s += max(0.0, tbb.xmax - (x_max - margin))
        s += max(0.0, (z_min + margin) - tbb.zmin)
        s += max(0.0, tbb.zmax - (z_max - margin))
        return s

    score = _overflow_score(text_bb)
    print(
        f"Text initial (fontsize={fontsize:.2f}, rotY={rot_about_y}) bbox: x[{text_bb.xmin:.3f},{text_bb.xmax:.3f}] z[{text_bb.zmin:.3f},{text_bb.zmax:.3f}] overflowScore={score:.4f}"
    )

    # If it still overflows in X (unlikely after rotation), reduce fontsize slightly until it fits.
    # This preserves the main intent (contained) at the cost of strict 10mm height if necessary.
    if score > 1e-6:
        for fs in [9.5, 9.0, 8.5, 8.0, 7.5]:
            cand = _make_text_solid(fs)
            cand_bb = cand.val().BoundingBox()
            cand_score = _overflow_score(cand_bb)
            print(
                f"  Trying fontsize={fs:.2f}: bbox x[{cand_bb.xmin:.3f},{cand_bb.xmax:.3f}] z[{cand_bb.zmin:.3f},{cand_bb.zmax:.3f}] overflowScore={cand_score:.4f}"
            )
            if cand_score <= 1e-6:
                text_wp = cand
                fontsize = fs
                score = cand_score
                break

        if score > 1e-6:
            print("WARNING: Could not fully contain text within pocket by bbox-check; proceeding with best attempt.")

    # Union the embossed text with the modified base
    wp_mod = wp_mod.union(text_wp)

    final_shape = wp_mod.val()
    fbb = final_shape.BoundingBox()
    print(f"Final BBox y[{fbb.ymin:.4f},{fbb.ymax:.4f}] (should remain 0..15)")

    return wp_mod
