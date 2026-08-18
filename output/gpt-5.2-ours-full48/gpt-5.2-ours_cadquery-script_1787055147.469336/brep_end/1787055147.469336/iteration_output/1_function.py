def my_cad_function(args):
    import cadquery as cq
    import os
    from cadquery import Vector

    def to_vec(p):
        """Convert CQ/OCCT point-like or tuple-like to cadquery.Vector."""
        if isinstance(p, Vector):
            return p
        if hasattr(p, "x") and hasattr(p, "y") and hasattr(p, "z"):
            return Vector(p.x, p.y, p.z)
        if isinstance(p, (tuple, list)) and len(p) == 3:
            return Vector(p[0], p[1], p[2])
        raise TypeError(f"Cannot convert to Vector: {type(p)} {p}")

    def point_inside_bbox(v, bb, eps=1e-6):
        return (bb.xmin - eps <= v.x <= bb.xmax + eps and
                bb.ymin - eps <= v.y <= bb.ymax + eps and
                bb.zmin - eps <= v.z <= bb.zmax + eps)

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

    bbox = base_shape.BoundingBox()
    bc = Vector(bbox.xmid, bbox.ymid, bbox.zmid)
    print(f"BBox min=({bbox.xmin:.3f},{bbox.ymin:.3f},{bbox.zmin:.3f}) max=({bbox.xmax:.3f},{bbox.ymax:.3f},{bbox.zmax:.3f})")
    print(f"BBox center=({bc.x:.3f},{bc.y:.3f},{bc.z:.3f})")

    # --- Choose a "vertical" planar face on the larger (left/head) region ---
    candidates = []
    faces = list(base_shape.Faces())
    print(f"Face count: {len(faces)}")

    for f in faces:
        # planar only
        try:
            if str(f.geomType()).upper() != "PLANE":
                continue
        except Exception:
            continue

        # centroid
        try:
            c = to_vec(f.Center())
        except Exception:
            continue

        # normal (robust attempts)
        n = None
        try:
            n = to_vec(f.normalAt())
        except Exception:
            try:
                u0, u1, v0, v1 = f._uvBounds()
                n = to_vec(f.normalAt(0.5 * (u0 + u1), 0.5 * (v0 + v1)))
            except Exception:
                n = None
        if n is None:
            continue

        try:
            n = n.normalized()
        except Exception:
            continue

        # vertical face => normal is mostly horizontal => |nz| small
        if abs(n.z) > 0.2:
            continue

        try:
            area = float(f.Area())
        except Exception:
            continue

        candidates.append((area, c, n, f))

    if not candidates:
        raise ValueError("No suitable vertical planar faces found (planar with |nz|<=0.2).")

    # Prefer big faces, then bias to left/head region (smaller x centroid)
    candidates.sort(key=lambda t: t[0], reverse=True)
    top = candidates[: min(8, len(candidates))]
    top.sort(key=lambda t: (t[0] * -1.0, t[1].x))  # primarily by area desc, then x asc

    # Among the top-by-area set, pick the one most on the left (head)
    best = min(top, key=lambda t: t[1].x)
    area, face_c, face_n, ref_face = best

    print("Chosen reference face:")
    print(f"  area={area:.3f}")
    print(f"  centroid=({face_c.x:.3f},{face_c.y:.3f},{face_c.z:.3f})")
    print(f"  normal=({face_n.x:.4f},{face_n.y:.4f},{face_n.z:.4f})")

    # --- Ring parameters (mm) ---
    outer_d = 40.0
    inner_d = 20.0
    thickness = 30.0
    R = outer_d / 2.0
    r = inner_d / 2.0

    # Small overlap to avoid a tangent-only (potentially non-manifold) join
    overlap = 0.5  # mm

    # out_dir: use face normal, but ensure it points outward from the body
    out_dir = face_n
    trial_center = face_c + out_dir * (R - overlap)
    if point_inside_bbox(trial_center, bbox, eps=1e-3):
        out_dir = out_dir * -1.0
    out_dir = out_dir.normalized()

    # axis_dir: in-plane direction, prefer global X projected onto plane
    x_axis = Vector(1, 0, 0)
    axis_dir = x_axis - out_dir * (x_axis.dot(out_dir))
    if axis_dir.Length < 1e-6:
        z_axis = Vector(0, 0, 1)
        axis_dir = z_axis - out_dir * (z_axis.dot(out_dir))
    if axis_dir.Length < 1e-6:
        y_axis = Vector(0, 1, 0)
        axis_dir = y_axis - out_dir * (y_axis.dot(out_dir))
    axis_dir = axis_dir.normalized()

    ring_center = face_c + out_dir * (R - overlap)

    print("Ring placement:")
    print(f"  ring_center=({ring_center.x:.3f},{ring_center.y:.3f},{ring_center.z:.3f})")
    print(f"  out_dir=({out_dir.x:.3f},{out_dir.y:.3f},{out_dir.z:.3f})")
    print(f"  axis_dir=({axis_dir.x:.3f},{axis_dir.y:.3f},{axis_dir.z:.3f})")

    # --- Build annular cylinder along axis_dir, centered at ring_center ---
    base_pt = ring_center - axis_dir * (thickness / 2.0)
    outer_cyl = cq.Solid.makeCylinder(R, thickness, base_pt, axis_dir)
    inner_cyl = cq.Solid.makeCylinder(r, thickness + 2.0, base_pt - axis_dir * 1.0, axis_dir)
    ring_solid = outer_cyl.cut(inner_cyl)

    ring_wp = cq.Workplane("XY").newObject([ring_solid])

    # --- Union with base model ---
    result = base_wp.union(ring_wp)

    return result
