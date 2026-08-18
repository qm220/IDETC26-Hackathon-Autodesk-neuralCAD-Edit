def my_cad_function(args):
    import cadquery as cq
    import os

    # --- Parameters (mm) ---
    W = 200.0      # 20 cm (left-right)
    H = 100.0      # 10 cm (up-down)
    DEPTH = 30.0   # 3 cm (into machine)
    R = 10.0       # 1 cm corner radius

    if "input_file" not in args:
        raise ValueError("Expected args['input_file'] for edit operation")

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shp = model.val() if hasattr(model, "val") else model
    if shp is None:
        raise ValueError("Failed to import STEP shape")

    bbox = shp.BoundingBox()
    c_model = bbox.center
    print(f"BBox: xmin={bbox.xmin:.3f} xmax={bbox.xmax:.3f} xlen={bbox.xlen:.3f}")
    print(f"      ymin={bbox.ymin:.3f} ymax={bbox.ymax:.3f} ylen={bbox.ylen:.3f}")
    print(f"      zmin={bbox.zmin:.3f} zmax={bbox.zmax:.3f} zlen={bbox.zlen:.3f}")
    print(f"BBox center: ({c_model.x:.3f}, {c_model.y:.3f}, {c_model.z:.3f})")

    # Based on the provided renders, Y is the vertical axis in this model.
    # We want a cut on the REAR face (front-back), so search for planar faces with normals ~ +/-Z.
    z_axis = cq.Vector(0, 0, 1)
    x_axis = cq.Vector(1, 0, 0)

    def safe_face_normal(face):
        ctr = face.Center()
        # normalAt(point)
        try:
            n = face.normalAt(cq.Vector(ctr.x, ctr.y, ctr.z))
            if n is not None:
                return n
        except Exception:
            pass
        # normalAt(u,v)
        try:
            u, v = face.paramAt(ctr)
            n = face.normalAt(u, v)
            if n is not None:
                return n
        except Exception:
            pass
        return None

    # Collect candidate planar +/-Z faces
    candidates = []
    for f in shp.Faces():
        try:
            if f.geomType() != "PLANE":
                continue
            n = safe_face_normal(f)
            if n is None:
                continue
            if abs(n.dot(z_axis)) < 0.85:
                continue
            area = float(f.Area())
            if area < 2000.0:
                continue
            bb = f.BoundingBox()
            ctr = f.Center()
            candidates.append({"face": f, "n": n, "area": area, "bb": bb, "ctr": ctr})
        except Exception:
            continue

    print(f"Candidate planar +/-Z faces: {len(candidates)}")
    if not candidates:
        print("No suitable rear/front planar faces found; returning original model")
        return model

    # Prefer the face closest to zmin (assumed rear). If none close enough, fall back to zmax.
    def dist_to_zmin(d):
        return abs(d["bb"].zmin - bbox.zmin)

    def dist_to_zmax(d):
        return abs(d["bb"].zmax - bbox.zmax)

    best_zmin = sorted(candidates, key=lambda d: (dist_to_zmin(d), -d["area"]))[0]
    best_zmax = sorted(candidates, key=lambda d: (dist_to_zmax(d), -d["area"]))[0]

    tol = 5.0  # mm tolerance for being "at" the rear/front extreme
    use_zmin = dist_to_zmin(best_zmin) <= min(dist_to_zmax(best_zmax), tol)
    chosen = best_zmin if use_zmin else best_zmax

    rear_face = chosen["face"]
    rear_n = chosen["n"]
    rear_bb = chosen["bb"]
    rear_ctr = chosen["ctr"]

    # Ensure cut direction points INTO the model
    v_to_center = cq.Vector(c_model.x - rear_ctr.x, c_model.y - rear_ctr.y, c_model.z - rear_ctr.z)
    n_in = rear_n
    if n_in.dot(v_to_center) < 0:
        n_in = n_in.multiply(-1)

    print(
        f"Chosen rear face: ctr=({rear_ctr.x:.2f},{rear_ctr.y:.2f},{rear_ctr.z:.2f}), "
        f"area={chosen['area']:.2f}, z-span=[{rear_bb.zmin:.3f},{rear_bb.zmax:.3f}]"
    )
    print(f"Chosen face dist to zmin={dist_to_zmin(chosen):.3f} dist to zmax={dist_to_zmax(chosen):.3f}")
    print(f"Using cut normal (into model): ({n_in.x:.3f},{n_in.y:.3f},{n_in.z:.3f})")

    # Placement: centered in X, low in Y (vertical), with bottom margin ~= side margin
    panel_width = rear_bb.xlen
    x_center = (rear_bb.xmin + rear_bb.xmax) / 2.0

    side_margin = (panel_width - W) / 2.0
    if side_margin < 0:
        print(f"WARNING: opening width {W} exceeds rear face width {panel_width:.2f}. Clamping side_margin to 0.")
        side_margin = 0.0

    bottom_margin = side_margin
    y_center = bbox.ymin + bottom_margin + H / 2.0

    # Clamp y_center to fit within chosen rear face Y-span
    y_min_allowed = rear_bb.ymin + H / 2.0 + 1.0
    y_max_allowed = rear_bb.ymax - H / 2.0 - 1.0
    if y_center < y_min_allowed:
        y_center = y_min_allowed
    if y_center > y_max_allowed:
        y_center = y_max_allowed

    print(f"Rear face x-span: [{rear_bb.xmin:.2f}, {rear_bb.xmax:.2f}] width={panel_width:.2f}")
    print(f"Rear face y-span: [{rear_bb.ymin:.2f}, {rear_bb.ymax:.2f}] height={rear_bb.ylen:.2f}")
    print(f"Computed margins: side_margin={side_margin:.2f} bottom_margin={bottom_margin:.2f}")
    print(f"Opening center target: x={x_center:.2f}, y={y_center:.2f}")

    # Define plane on rear face at the desired center
    x_dir = x_axis
    if abs(n_in.dot(x_dir)) > 0.95:
        x_dir = cq.Vector(0, 1, 0)

    origin = cq.Vector(x_center, y_center, rear_ctr.z)
    plane = cq.Plane(origin=origin, normal=n_in, xDir=x_dir)

    cutter = (
        cq.Workplane(plane)
        .sketch()
        .rect(W, H)
        .vertices()
        .fillet(R)
        .finalize()
        .extrude(DEPTH)
    )

    result = model.cut(cutter)
    print("Applied rear opening cut: 200x100 mm, depth 30 mm, corner radius 10 mm.")

    return result
