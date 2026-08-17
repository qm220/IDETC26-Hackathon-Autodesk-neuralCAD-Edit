def my_cad_function(args):
    import os
    import cadquery as cq

    if "input_file" not in args:
        print("No input_file provided")
        return None

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)

    # Get underlying OCC shape
    occ = model.val() if hasattr(model, "val") else model

    print(f"Loaded STEP: {input_file}")
    print(f"Valid: {occ.isValid()}")
    print(f"Solids: {len(occ.Solids())}, Faces: {len(occ.Faces())}, Edges: {len(occ.Edges())}")

    bbox = occ.BoundingBox()
    xmid = 0.5 * (bbox.xmin + bbox.xmax)
    ymid = 0.5 * (bbox.ymin + bbox.ymax)
    zmid = 0.5 * (bbox.zmin + bbox.zmax)
    print(f"Overall BBox: xmin={bbox.xmin:.3f} xmax={bbox.xmax:.3f} ymin={bbox.ymin:.3f} ymax={bbox.ymax:.3f} zmin={bbox.zmin:.3f} zmax={bbox.zmax:.3f}")
    print(f"Overall Center: x={xmid:.3f}, y={ymid:.3f}, z={zmid:.3f}")

    # Heuristic: find a cylindrical face near the 'front' (max Y) and near X center.
    # We'll assume the fillet we need to remove is represented by a CYLINDER face.
    cyl_candidates = []
    for i, f in enumerate(occ.Faces()):
        try:
            gt = f.geomType()
        except Exception:
            continue
        if str(gt).upper() != "CYLINDER":
            continue
        fb = f.BoundingBox()
        fc = fb.center
        # Prefer faces near front (ymax) and near x-center
        score = abs(bbox.ymax - fc.y) + 0.25 * abs(fc.x - xmid)
        cyl_candidates.append((score, i, f, fb, fc))

    cyl_candidates.sort(key=lambda t: t[0])
    print(f"Cylindrical faces found: {len(cyl_candidates)}")
    for k, (score, i, f, fb, fc) in enumerate(cyl_candidates[:8]):
        print(
            f"  cand[{k}] faceIndex={i} score={score:.4f} center=({fc.x:.3f},{fc.y:.3f},{fc.z:.3f}) "
            f"bb=({fb.xlen:.3f},{fb.ylen:.3f},{fb.zlen:.3f}) "
            f"y_to_front={abs(bbox.ymax-fc.y):.3f} x_to_mid={abs(fc.x-xmid):.3f}"
        )

    # If no cylinder found, just return the model (with debug output)
    if not cyl_candidates:
        print("No CYLINDER faces detected; cannot reliably remove fillet. Returning original.")
        return model

    # Pick best candidate
    _, _, fillet_face, fb, fc = cyl_candidates[0]

    # Decide if this fillet runs along X or Z based on its bounding box
    axis = "X" if fb.xlen >= fb.zlen else "Z"

    chamfer = 1.0  # mm
    extra = 0.25   # small oversize to ensure we fully remove the fillet

    base = cq.Workplane("XY").add(occ)

    # Build a cutting wedge that creates a 1mm chamfer at the supposed front edge region.
    # This is an approximation that should remove the existing fillet and leave a planar chamfer.
    if axis == "X":
        # Edge runs along X; create triangle in YZ and extrude along X over local region.
        is_top = abs(fb.zmax - bbox.zmax) <= abs(fb.zmin - bbox.zmin)
        y_front = bbox.ymax
        if is_top:
            z_ref = bbox.zmax
            pts = [
                (y_front + 0.0, z_ref + 0.0),
                (y_front - (chamfer + extra), z_ref + 0.0),
                (y_front + 0.0, z_ref - (chamfer + extra)),
            ]
        else:
            z_ref = bbox.zmin
            pts = [
                (y_front + 0.0, z_ref + 0.0),
                (y_front - (chamfer + extra), z_ref + 0.0),
                (y_front + 0.0, z_ref + (chamfer + extra)),
            ]

        x0 = fb.xmin - 2.0
        xlen = fb.xlen + 4.0

        print(f"Selected candidate axis={axis}, is_top={is_top}, wedge x0={x0:.3f}, xlen={xlen:.3f}")
        print(f"Wedge triangle (YZ) pts: {pts}")

        wedge = (
            cq.Workplane("YZ")
            .workplane(offset=x0)
            .polyline(pts)
            .close()
            .extrude(xlen)
        )

    else:
        # Edge runs along Z; create triangle in XY and extrude along Z over local region.
        y_front = bbox.ymax
        # Decide which side in X is closest to the candidate
        dist_to_maxx = abs(fb.xmax - bbox.xmax)
        dist_to_minx = abs(fb.xmin - bbox.xmin)
        use_maxx = dist_to_maxx <= dist_to_minx
        x_side = bbox.xmax if use_maxx else bbox.xmin
        # Move inward in X depending on which side
        x_in = x_side - (chamfer + extra) if use_maxx else x_side + (chamfer + extra)

        pts = [
            (x_side + 0.0, y_front + 0.0),
            (x_in, y_front + 0.0),
            (x_side + 0.0, y_front - (chamfer + extra)),
        ]

        z0 = fb.zmin - 2.0
        zlen = fb.zlen + 4.0

        print(f"Selected candidate axis={axis}, use_maxx={use_maxx}, wedge z0={z0:.3f}, zlen={zlen:.3f}")
        print(f"Wedge triangle (XY) pts: {pts}")

        wedge = (
            cq.Workplane("XY")
            .workplane(offset=z0)
            .polyline(pts)
            .close()
            .extrude(zlen)
        )

    try:
        result = base.cut(wedge)
        print("Applied wedge cut to remove front-center fillet region and form chamfer.")
        return result
    except Exception as e:
        print(f"Cut operation failed: {e}")
        return model
