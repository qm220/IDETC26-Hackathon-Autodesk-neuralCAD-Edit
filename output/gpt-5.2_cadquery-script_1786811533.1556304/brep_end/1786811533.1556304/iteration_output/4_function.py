def my_cad_function(args):
    import os
    import cadquery as cq

    rib_t = 1.5  # mm rib thickness

    if "input_file" not in args:
        print("No input_file provided; cannot edit model.")
        return None

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shp = model.val() if hasattr(model, "val") else model

    bbox = shp.BoundingBox()
    cx, cy, cz = bbox.center.x, bbox.center.y, bbox.center.z
    xlen, ylen, zlen = bbox.xlen, bbox.ylen, bbox.zlen

    print("Loaded STEP:", input_file)
    print(f"Valid: {shp.isValid()}")
    print(f"BBOX center=({cx:.3f},{cy:.3f},{cz:.3f})")
    print(f"BBOX lens x={xlen:.3f} y={ylen:.3f} z={zlen:.3f}")

    # --- Detect a large side face (normal ~ +/-Y) and a bottom face (normal ~ +/-Z near zmin) ---
    side_face = None
    side_area = -1.0
    side_c = None
    side_n = None

    bottom_face = None
    bottom_score = -1.0
    bottom_c = None
    bottom_n = None

    faces = shp.Faces()
    print(f"Faces: {len(faces)}")

    for f in faces:
        try:
            if hasattr(f, "geomType") and f.geomType() != "PLANE":
                continue
            n = f.normalAt()
            a = f.Area()
            c = f.Center()
        except Exception:
            continue

        # side face candidate
        if abs(n.y) > 0.90 and abs(n.x) < 0.35 and abs(n.z) < 0.35:
            if a > side_area:
                side_face, side_area, side_c, side_n = f, a, c, n

        # bottom face candidate: planar, mostly +/-Z, and close to bbox.zmin
        if abs(n.z) > 0.90 and abs(n.x) < 0.35 and abs(n.y) < 0.35:
            # prefer large area and closeness to zmin
            clos = abs(c.z - bbox.zmin)
            score = a / (1.0 + 10.0 * clos)  # strongly favor zmin
            if score > bottom_score:
                bottom_face, bottom_score, bottom_c, bottom_n = f, score, c, n

    # Fallback to bbox planes if detection fails
    if side_face is None:
        print("WARNING: Could not detect a dominant +/-Y side face; using bbox.ymin.")
        side_y = bbox.ymin
        interior_y_dir = +1.0
    else:
        side_y = side_c.y
        # decide whether this is ymin or ymax side
        at_ymin = abs(side_y - bbox.ymin) <= abs(side_y - bbox.ymax)
        interior_y_dir = +1.0 if at_ymin else -1.0
        print(
            f"Side face: area={side_area:.3f}, center=({side_c.x:.3f},{side_c.y:.3f},{side_c.z:.3f}), "
            f"normal=({side_n.x:.3f},{side_n.y:.3f},{side_n.z:.3f}), using {'ymin' if at_ymin else 'ymax'}"
        )

    if bottom_face is None:
        print("WARNING: Could not detect a bottom face near zmin; using bbox.zmin.")
        bottom_z = bbox.zmin
        interior_z_dir = +1.0
    else:
        bottom_z = bottom_c.z
        at_zmin = abs(bottom_z - bbox.zmin) <= abs(bottom_z - bbox.zmax)
        interior_z_dir = +1.0 if at_zmin else -1.0
        print(
            f"Bottom face: center=({bottom_c.x:.3f},{bottom_c.y:.3f},{bottom_c.z:.3f}), "
            f"normal=({bottom_n.x:.3f},{bottom_n.y:.3f},{bottom_n.z:.3f}), using {'zmin' if at_zmin else 'zmax'}"
        )

    # --- Create a triangular gusset rib in the YZ plane at x=cx, thickness=1.5mm along X ---
    eps = 0.15  # overlap helper

    # Leg lengths: keep reasonable for this part size
    Ly = max(2.5, min(0.60 * ylen, 4.5))
    Lz = max(3.5, min(0.55 * zlen, 6.5))

    y0 = side_y + interior_y_dir * eps
    z0 = bottom_z + interior_z_dir * eps
    y1 = y0 + interior_y_dir * Ly
    z1 = z0 + interior_z_dir * Lz

    tri = [(y0, z0), (y1, z0), (y0, z1)]
    print(f"Rib thickness={rib_t}mm")
    print(f"Rib YZ right-triangle pts (at x={cx:.3f}): {tri}")

    rib = (
        cq.Workplane("YZ", origin=(cx, 0, 0))
        .polyline(tri)
        .close()
        .extrude(rib_t, both=True)
    )

    # Union with original
    vol0 = None
    try:
        vol0 = shp.Volume()
    except Exception:
        pass

    try:
        result = cq.Workplane(obj=shp).union(rib)
    except Exception as e:
        print("Union via Workplane(obj=shp) failed; trying model.union. Error:", e)
        result = model.union(rib)

    # Debug: volume delta and new bbox
    try:
        res_shape = result.val() if hasattr(result, "val") else result
        if vol0 is not None:
            print(f"Volume before: {vol0:.3f} mm^3")
            print(f"Volume after : {res_shape.Volume():.3f} mm^3")
            print(f"Delta volume : {res_shape.Volume() - vol0:.3f} mm^3")
        rb = res_shape.BoundingBox()
        print(f"New BBOX lens x={rb.xlen:.3f} y={rb.ylen:.3f} z={rb.zlen:.3f}")
    except Exception as e:
        print("Post-union analysis failed:", e)

    print("Done: added a 1.5mm thick triangular reinforcement rib.")
    return result
