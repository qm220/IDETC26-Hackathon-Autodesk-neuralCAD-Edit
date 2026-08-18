def my_cad_function(args):
    import os, math
    import cadquery as cq

    # --- Load base model ---
    if "input_file" not in args:
        raise ValueError("Expected args['input_file'] for edit task")
    input_file = os.path.expanduser(args["input_file"])
    base = cq.importers.importStep(input_file)
    base_shape = base.val() if hasattr(base, "val") else base

    print(f"Loaded STEP: {input_file}")
    print(f"Base valid: {base_shape.isValid()}")
    print(f"Base faces: {len(base_shape.Faces())}")

    # --- Find the 'flat end face' (planar face normal ~ +/-X with maximum X center) ---
    cand = []
    for f in base_shape.Faces():
        try:
            if f.geomType() != "PLANE":
                continue
            c = f.Center()
            # Use center point parameters to get a stable normal
            n = f.normalAt(c)
            if abs(n.x) > 0.90:  # face normal aligned with X
                cand.append((c.x, f, c, n))
        except Exception:
            continue

    if not cand:
        raise RuntimeError("Could not find any planar end faces with normal aligned to X")

    cand.sort(key=lambda t: t[0])
    x_end, end_face, end_center, end_normal = cand[-1]

    bb_f = end_face.BoundingBox()
    yc = 0.5 * (bb_f.ymin + bb_f.ymax)
    zc = 0.5 * (bb_f.zmin + bb_f.zmax)

    print("End-face candidates (count):", len(cand))
    print(f"Chosen end face center: ({end_center.x:.4f}, {end_center.y:.4f}, {end_center.z:.4f})")
    print(f"Chosen end face approx normal: ({end_normal.x:.4f}, {end_normal.y:.4f}, {end_normal.z:.4f})")
    print(f"Chosen end face bbox y:[{bb_f.ymin:.3f},{bb_f.ymax:.3f}] z:[{bb_f.zmin:.3f},{bb_f.zmax:.3f}] -> (yc,zc)=({yc:.3f},{zc:.3f})")

    # --- Bearing parameters (small enough to fit end face, yet visible) ---
    bearing_od = 0.9   # mm
    bearing_id = 0.5   # mm
    bearing_len = 6.0  # mm extrusion along +X
    pitch_r = 1.4      # mm offset radius for circular pattern in YZ
    overlap = 0.2      # mm extrude slightly into bar to guarantee union

    # 8 instances total (original + 7 additional)
    n_inst = 8
    pts = []
    for i in range(n_inst):
        a = 2.0 * math.pi * i / n_inst
        pts.append((pitch_r * math.cos(a), pitch_r * math.sin(a)))  # (localY, localZ)

    # Build the patterned annular bosses on a YZ workplane located at the end face.
    # Use x_end - overlap so that the extrusion overlaps the existing end face volume.
    bearing_wp = (
        cq.Workplane("YZ", origin=(x_end - overlap, yc, zc))
        .pushPoints(pts)
        .circle(bearing_od / 2.0)
        .circle(bearing_id / 2.0)
        .extrude(bearing_len + overlap, combine=False)
    )

    # Union to the original part
    result = cq.Workplane(obj=base_shape).union(bearing_wp)

    # Debug: bounding box after union
    out_bb = result.val().BoundingBox()
    print(f"Result bbox: x[{out_bb.xmin:.3f},{out_bb.xmax:.3f}] y[{out_bb.ymin:.3f},{out_bb.ymax:.3f}] z[{out_bb.zmin:.3f},{out_bb.zmax:.3f}]")

    return result
