def my_cad_function(args):
    import cadquery as cq
    import os

    input_file = os.path.expanduser(args.get("input_file", ""))
    if not input_file or not os.path.exists(input_file):
        raise ValueError(f"Missing/invalid args['input_file']: {input_file}")

    imp = cq.importers.importStep(input_file)
    base_shape = imp.val() if hasattr(imp, "val") else imp
    wp = cq.Workplane("XY").newObject([base_shape])

    bb = base_shape.BoundingBox()
    ymin, ymax = bb.ymin, bb.ymax
    print(
        f"Loaded STEP. BBox: x[{bb.xmin:.4f},{bb.xmax:.4f}] y[{ymin:.4f},{ymax:.4f}] z[{bb.zmin:.4f},{bb.zmax:.4f}]"
    )

    def _area(f):
        try:
            return float(f.Area())
        except Exception:
            return 0.0

    def _wp_on_y(yval, x0=0.0, z0=0.0):
        # Plane parallel to XZ (normal +Y), origin at (x0,yval,z0)
        pl = cq.Plane(origin=(x0, yval, z0), normal=(0, 1, 0), xDir=(1, 0, 0))
        return cq.Workplane(pl)

    # ------------------------
    # Locate existing TOP pocket floor face (planar, normal +Y, near y=ymax-1)
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

    # Pocket footprint extents from outer wire vertices
    ow = pocket_face.outerWire()
    pts = [v.Center() for v in ow.Vertices()]
    xs = [p.x for p in pts]
    zs = [p.z for p in pts]
    x_min, x_max = min(xs), max(xs)
    z_min, z_max = min(zs), max(zs)
    x_len, z_len = (x_max - x_min), (z_max - z_min)
    x_c, z_c = (x_min + x_max) / 2.0, (z_min + z_max) / 2.0

    # Estimate corner fillet radius from circular edges on the outer wire; fallback 1mm
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
    # 1) Bottom mirrored recessed plateau (cut)
    plateau_depth = 1.0

    # Build a filleted-rectangle solid tool from the BOTTOM face, centered at pocket center.
    # Extrude upward (+Y) by 1mm, then cut it from the body.
    bottom_wp = _wp_on_y(ymin, x0=x_c, z0=z_c)

    def _filleted_rect_solid(workplane, w, h, fillet_r, extrude_h):
        # Prefer Sketch fillet (2D), fallback to 3D fillet on the prism.
        try:
            sk = cq.Sketch().rect(w, h).fillet(fillet_r)
            return workplane.placeSketch(sk).extrude(extrude_h)
        except Exception as e:
            print(f"Sketch fillet path failed ({e}); falling back to 3D fillet on extruded rectangle.")
            return (
                workplane
                .rect(w, h)
                .extrude(extrude_h)
                .edges("|Y")
                .fillet(fillet_r)
            )

    bottom_tool = _filleted_rect_solid(bottom_wp, x_len, z_len, r_fillet, plateau_depth)
    wp = wp.cut(bottom_tool)

    # ------------------------
    # 2) Embossed text "TOP" on top pocket floor, 10mm high, 1mm raised (flush to global top)
    emboss_h = 1.0
    fontsize = 10.0

    # Create text on the pocket floor plane, centered at pocket center.
    # Rotate IN-PLANE by 90deg about plane normal (local Z) so the word runs along the long pocket direction.
    top_wp = _wp_on_y(y_pocket, x0=x_c, z0=z_c).transformed(rotate=(0, 0, 90))

    try:
        text_solid_wp = top_wp.text(
            "TOP",
            fontsize,
            emboss_h,
            font="Arial",
            halign="center",
            valign="center",
            combine=False,
        )
    except Exception as e1:
        print(f"Arial/font kw not supported ({e1}); falling back to default font.")
        text_solid_wp = top_wp.text(
            "TOP",
            fontsize,
            emboss_h,
            halign="center",
            valign="center",
            combine=False,
        )

    text_solid = text_solid_wp.val()

    # Clip text strictly to the plateau footprint (plan-view containment guarantee)
    clip_vol = _filleted_rect_solid(_wp_on_y(y_pocket, x0=x_c, z0=z_c), x_len, z_len, r_fillet, emboss_h)
    clipped_text = cq.Workplane("XY").newObject([text_solid.intersect(clip_vol.val())])

    # Union embossed text into the part
    wp = wp.union(clipped_text)

    final_shape = wp.val()
    fbb = final_shape.BoundingBox()
    print(f"Final BBox y[{fbb.ymin:.4f},{fbb.ymax:.4f}] (expected to remain ~[{ymin:.4f},{ymax:.4f}])")

    # Extra sanity print: check if anything protrudes above original top
    if fbb.ymax > ymax + 1e-3:
        print(f"WARNING: Geometry protrudes above original top by {fbb.ymax - ymax:.4f}mm")

    return wp
