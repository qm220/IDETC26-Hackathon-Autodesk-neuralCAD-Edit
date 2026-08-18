def my_cad_function(args):
    import cadquery as cq
    import os

    # --- Parameters (mm) ---
    W = 200.0      # 20 cm
    H = 100.0      # 10 cm
    DEPTH = 30.0   # 3 cm
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

    y_axis = cq.Vector(0, 1, 0)

    def safe_face_normal(face):
        ctr = face.Center()
        # Try normalAt(point)
        try:
            n = face.normalAt(cq.Vector(ctr.x, ctr.y, ctr.z))
            if n is not None:
                return n
        except Exception:
            pass
        # Try normalAt(u,v)
        try:
            u, v = face.paramAt(ctr)
            n = face.normalAt(u, v)
            if n is not None:
                return n
        except Exception:
            pass
        return None

    # Collect candidate planar +/-Y faces
    candidates = []
    for f in shp.Faces():
        try:
            if f.geomType() != "PLANE":
                continue
            n = safe_face_normal(f)
            if n is None:
                continue
            if abs(n.dot(y_axis)) < 0.80:
                continue
            area = float(f.Area())
            if area < 1000.0:
                continue
            ctr = f.Center()
            fbb = f.BoundingBox()
            candidates.append({"face": f, "area": area, "ctr": ctr, "n": n, "bb": fbb})
        except Exception:
            continue

    print(f"Candidate planar +/-Y faces: {len(candidates)}")
    if not candidates:
        print("No suitable planar rear/front faces found; returning original model")
        return model

    # Pick a rear face: closest to overall bbox.ymin, with largest area tie-break
    candidates_sorted = sorted(
        candidates,
        key=lambda d: (abs(d["bb"].ymin - bbox.ymin), -d["area"])  # near rear extreme, then largest
    )
    chosen = candidates_sorted[0]

    rear_face = chosen["face"]
    rear_ctr = chosen["ctr"]
    rear_n = chosen["n"]
    rear_bb = rear_face.BoundingBox()

    # Ensure cut direction points INTO the model
    v_to_center = cq.Vector(c_model.x - rear_ctr.x, c_model.y - rear_ctr.y, c_model.z - rear_ctr.z)
    n_in = rear_n
    if n_in.dot(v_to_center) < 0:
        n_in = n_in.multiply(-1)

    print(f"Chosen rear face: center=({rear_ctr.x:.2f},{rear_ctr.y:.2f},{rear_ctr.z:.2f}), area={chosen['area']:.2f}")
    print(f"Rear face y-range: [{rear_bb.ymin:.3f}, {rear_bb.ymax:.3f}] vs model ymin={bbox.ymin:.3f}")
    print(f"Using cut normal (into model): ({n_in.x:.3f},{n_in.y:.3f},{n_in.z:.3f})")

    # Compute placement
    panel_width = rear_bb.xlen
    x_center = (rear_bb.xmin + rear_bb.xmax) / 2.0

    side_margin = (panel_width - W) / 2.0
    if side_margin < 0:
        print(f"WARNING: requested opening width {W} exceeds rear face width {panel_width:.2f}. Clamping margin to 0.")
        side_margin = 0.0
    bottom_margin = side_margin  # per request: bottom margin ~ equals side margin

    z_center = bbox.zmin + bottom_margin + H / 2.0

    # Clamp z_center to fit within the chosen rear face's Z span (with small safety offset)
    z_min_allowed = rear_bb.zmin + H / 2.0 + 1.0
    z_max_allowed = rear_bb.zmax - H / 2.0 - 1.0
    if z_center < z_min_allowed:
        z_center = z_min_allowed
    if z_center > z_max_allowed:
        z_center = z_max_allowed

    print(f"Rear face x-span: [{rear_bb.xmin:.2f}, {rear_bb.xmax:.2f}] (width={panel_width:.2f})")
    print(f"Computed margins: side_margin={side_margin:.2f} bottom_margin={bottom_margin:.2f}")
    print(f"Opening center target: x={x_center:.2f}, z={z_center:.2f}")

    # Build a workplane on the rear face at desired opening center
    x_dir = cq.Vector(1, 0, 0)
    if abs(n_in.dot(x_dir)) > 0.95:
        x_dir = cq.Vector(0, 0, 1)

    origin = cq.Vector(x_center, rear_ctr.y, z_center)
    plane = cq.Plane(origin=origin, normal=n_in, xDir=x_dir)

    # Build cutter solid with a *sketch* fillet (NOT a 3D fillet)
    cutter = (
        cq.Workplane(plane)
        .sketch()
        .rect(W, H)
        .vertices()
        .fillet(R)
        .finalize()
        .extrude(DEPTH)
    )

    # Cut from the whole imported compound/assembly
    result = model.cut(cutter)
    print("Applied rear opening cut: 200x100 mm, depth 30 mm, corner radius 10 mm.")

    return result
