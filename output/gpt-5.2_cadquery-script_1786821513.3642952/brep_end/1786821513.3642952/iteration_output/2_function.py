def my_cad_function(args):
    import os
    import math
    import cadquery as cq

    if "input_file" not in args:
        print("No input_file provided")
        return None

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    occ = model.val() if hasattr(model, "val") else model

    print(f"Loaded STEP: {input_file}")
    print(f"Valid: {occ.isValid()}")
    print(f"Solids: {len(occ.Solids())}, Faces: {len(occ.Faces())}, Edges: {len(occ.Edges())}")

    bbox = occ.BoundingBox()
    xmid = 0.5 * (bbox.xmin + bbox.xmax)
    zmid = 0.5 * (bbox.zmin + bbox.zmax)
    y_front = bbox.ymax
    print(
        f"Overall BBox: xmin={bbox.xmin:.3f} xmax={bbox.xmax:.3f} "
        f"ymin={bbox.ymin:.3f} ymax={bbox.ymax:.3f} "
        f"zmin={bbox.zmin:.3f} zmax={bbox.zmax:.3f}"
    )

    chamfer = 1.0  # mm
    y_tol = 3.5    # search band near front
    eps = 0.05

    # --- Find a center cylindrical face near the front; prefer a "hub/boss" size radius ---
    cyl_cands = []
    for i, f in enumerate(occ.Faces()):
        try:
            if str(f.geomType()).upper() != "CYLINDER":
                continue
        except Exception:
            continue

        fb = f.BoundingBox()
        fc = fb.center

        # cylinder axis ~Y implies xlen ~ zlen (diameter) and the face is near center in XZ
        if abs(fb.xlen - fb.zlen) > 1.0:
            continue

        # close to model center in XZ
        radial_center = math.hypot(fc.x - xmid, fc.z - zmid)
        if radial_center > 3.0:
            continue

        # close to front (ymax)
        if (y_front - fb.ymax) > y_tol:
            continue

        # estimated radius from bbox diameter
        r = 0.25 * (fb.xlen + fb.zlen)

        # focus on "front center" feature, avoid outer rim
        if r < 5.0 or r > 30.0:
            continue

        score = (y_front - fb.ymax) + 0.05 * radial_center - 0.01 * r  # prefer closer-to-front and larger hub radius
        cyl_cands.append((score, r, i, fb, fc))

    cyl_cands.sort(key=lambda t: t[0])
    print(f"Center/front CYLINDER candidates (filtered): {len(cyl_cands)}")
    for k, (score, r, i, fb, fc) in enumerate(cyl_cands[:12]):
        print(
            f"  cand[{k}] faceIndex={i} score={score:.4f} r~{r:.3f} "
            f"ymax={fb.ymax:.3f} y_to_front={y_front - fb.ymax:.3f} "
            f"bb=({fb.xlen:.3f},{fb.ylen:.3f},{fb.zlen:.3f}) center=({fc.x:.3f},{fc.y:.3f},{fc.z:.3f})"
        )

    if not cyl_cands:
        print("No suitable center/front CYLINDER faces found; returning original.")
        return model

    # Choose the largest radius among the best few (helps pick the outer boss around the center)
    top = cyl_cands[:8]
    r_target = max(top, key=lambda t: t[1])[1]
    print(f"Selected target hub radius r_target~{r_target:.3f} mm for front chamfer.")

    # --- Build an annular frustum cutter to replace the existing fillet with a 1mm chamfer ---
    # We cut only in a small Y band near the front.
    y1 = y_front + eps
    y0 = y_front - chamfer - eps
    dy = y1 - y0

    # Outer boundary matches the (approx) cylindrical outer surface radius
    r_outer = r_target + eps
    # Inner boundary defines the chamfer plane: from r_outer at y0 to (r_outer - chamfer) at y1
    r_inner_front = max(0.1, r_outer - chamfer - 0.02)

    wp0 = cq.Workplane("XZ").workplane(offset=y0).center(xmid, zmid)

    try:
        outer_cyl = wp0.circle(r_outer).extrude(dy)
        inner_cone = (
            wp0.circle(r_outer)
            .workplane(offset=dy)
            .circle(r_inner_front)
            .loft(combine=False)
        )
        cutter = outer_cyl.cut(inner_cone)

        result = cq.Workplane("XY").add(occ).cut(cutter)
        print(
            "Applied annular frustum cut at front center to remove fillet region and create ~1mm chamfer."
        )
        return result

    except Exception as e:
        print(f"Chamfer cutter operation failed: {e}")
        return model
