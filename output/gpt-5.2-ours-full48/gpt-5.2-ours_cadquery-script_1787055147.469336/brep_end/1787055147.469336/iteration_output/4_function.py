def my_cad_function(args):
    import cadquery as cq
    import os
    from cadquery import Vector

    def v(x, y, z):
        return Vector(float(x), float(y), float(z))

    def bbox_center(bb):
        return v((bb.xmin + bb.xmax) * 0.5, (bb.ymin + bb.ymax) * 0.5, (bb.zmin + bb.zmax) * 0.5)

    def point_inside_bbox(p, bb, eps=1e-6):
        return (bb.xmin - eps <= p.x <= bb.xmax + eps and
                bb.ymin - eps <= p.y <= bb.ymax + eps and
                bb.zmin - eps <= p.z <= bb.zmax + eps)

    # --- Load input STEP ---
    input_path = args.get("input_file", None)
    if not input_path:
        raise ValueError("args['input_file'] is required")
    input_path = os.path.expanduser(input_path)
    if not os.path.exists(input_path):
        raise ValueError(f"Missing STEP at: {input_path}")

    base_wp = cq.importers.importStep(input_path)
    base_shape = base_wp.val() if hasattr(base_wp, "val") else base_wp

    print(f"Loaded STEP: {input_path}")
    try:
        print(f"Valid: {base_shape.isValid()}")
    except Exception:
        pass

    model_bb = base_shape.BoundingBox()
    model_c = bbox_center(model_bb)
    print(f"Model BBox min=({model_bb.xmin:.3f},{model_bb.ymin:.3f},{model_bb.zmin:.3f}) max=({model_bb.xmax:.3f},{model_bb.ymax:.3f},{model_bb.zmax:.3f})")
    print(f"Model BBox center=({model_c.x:.3f},{model_c.y:.3f},{model_c.z:.3f})")

    # --- Find the intended reference face: vertical planar face on the bigger head feature ---
    faces = list(base_shape.Faces())
    print(f"Face count: {len(faces)}")

    candidates = []
    for f in faces:
        try:
            if str(f.geomType()).upper() != "PLANE":
                continue
        except Exception:
            continue

        # Normal
        try:
            n = Vector(*f.normalAt().toTuple()).normalized()
        except Exception:
            try:
                u0, u1, v0, v1 = f._uvBounds()
                n = Vector(*f.normalAt(0.5 * (u0 + u1), 0.5 * (v0 + v1)).toTuple()).normalized()
            except Exception:
                continue

        # vertical plane => normal mostly horizontal
        if abs(n.z) > 0.2:
            continue

        # prefer faces whose normals are close to +/-Y
        if abs(n.y) < 0.85:
            continue

        try:
            area = float(f.Area())
        except Exception:
            continue

        fbb = f.BoundingBox()
        fc = bbox_center(fbb)

        d_extreme = min(abs(fc.y - model_bb.ymin), abs(fc.y - model_bb.ymax))
        candidates.append((d_extreme, -area, fc, n, f))

    if not candidates:
        print("No +/-Y vertical planar faces found; falling back to any vertical planar face selection")
        candidates = []
        for f in faces:
            try:
                if str(f.geomType()).upper() != "PLANE":
                    continue
            except Exception:
                continue
            try:
                n = Vector(*f.normalAt().toTuple()).normalized()
            except Exception:
                continue
            if abs(n.z) > 0.2:
                continue
            try:
                area = float(f.Area())
            except Exception:
                continue
            fbb = f.BoundingBox()
            fc = bbox_center(fbb)
            candidates.append((999.0, -area, fc, n, f))

    candidates.sort(key=lambda t: (t[0], t[1]))
    d_extreme, neg_area, face_center, face_n, ref_face = candidates[0]
    area = -neg_area

    print("Chosen reference face (intended: head-side vertical face):")
    print(f"  d_to_y_extreme={d_extreme:.3f}")
    print(f"  area={area:.3f}")
    print(f"  face_bbox_center=({face_center.x:.3f},{face_center.y:.3f},{face_center.z:.3f})")
    print(f"  normal=({face_n.x:.4f},{face_n.y:.4f},{face_n.z:.4f})")

    # --- Ring parameters (mm) ---
    outer_d = 40.0
    inner_d = 20.0
    thickness = 30.0
    R = outer_d / 2.0
    r = inner_d / 2.0

    # Small overlap to ensure boolean union is robust (pure tangency can be non-manifold)
    overlap = 0.2  # mm

    out_dir = face_n.normalized()
    test_pt = face_center + out_dir * (R - overlap)
    if point_inside_bbox(test_pt, model_bb, eps=1e-3):
        out_dir = out_dir * -1.0
    out_dir = out_dir.normalized()

    # Axis direction must be parallel to the reference face (in-plane)
    x_axis = v(1, 0, 0)
    axis_dir = x_axis - out_dir * (x_axis.dot(out_dir))
    if axis_dir.Length < 1e-6:
        z_axis = v(0, 0, 1)
        axis_dir = z_axis - out_dir * (z_axis.dot(out_dir))
    axis_dir = axis_dir.normalized()

    ring_center = face_center + out_dir * (R - overlap)

    print("Ring placement:")
    print(f"  ring_center=({ring_center.x:.3f},{ring_center.y:.3f},{ring_center.z:.3f})")
    print(f"  out_dir=({out_dir.x:.3f},{out_dir.y:.3f},{out_dir.z:.3f})")
    print(f"  axis_dir=({axis_dir.x:.3f},{axis_dir.y:.3f},{axis_dir.z:.3f})")

    base_pt = ring_center - axis_dir * (thickness / 2.0)

    outer_cyl = cq.Solid.makeCylinder(R, thickness, base_pt, axis_dir)
    inner_cyl = cq.Solid.makeCylinder(r, thickness + 2.0, base_pt - axis_dir * 1.0, axis_dir)
    ring_solid = outer_cyl.cut(inner_cyl)

    result = base_wp.union(cq.Workplane("XY").newObject([ring_solid]))

    return result
