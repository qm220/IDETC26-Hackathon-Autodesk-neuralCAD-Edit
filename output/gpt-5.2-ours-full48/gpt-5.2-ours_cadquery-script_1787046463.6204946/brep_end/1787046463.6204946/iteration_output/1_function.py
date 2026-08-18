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
    print(f"BBox: xmin={bbox.xmin:.3f} xmax={bbox.xmax:.3f} xlen={bbox.xlen:.3f}")
    print(f"      ymin={bbox.ymin:.3f} ymax={bbox.ymax:.3f} ylen={bbox.ylen:.3f}")
    print(f"      zmin={bbox.zmin:.3f} zmax={bbox.zmax:.3f} zlen={bbox.zlen:.3f}")
    c_model = bbox.center
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

    # Collect candidate planar rear/front faces (normal ~ +/-Y)
    candidates = []  # dicts with face, area, center, normal, fbb
    for f in shp.Faces():
        try:
            if f.geomType() != "PLANE":
                continue
            n = safe_face_normal(f)
            if n is None:
                continue
            if abs(n.dot(y_axis)) < 0.80:
                continue
            ctr = f.Center()
            fbb = f.BoundingBox()
            candidates.append({
                "face": f,
                "area": float(f.Area()),
                "ctr": ctr,
                "n": n,
                "bb": fbb,
            })
        except Exception:
            continue

    print(f"Candidate planar +/-Y faces: {len(candidates)}")
    if not candidates:
        print("No suitable planar +/-Y faces found; returning original model")
        return model

    def pick_at_extreme(which="ymin"):
        # Use face bounding box against model bounding box extremes (more robust than face center)
        for tol in [10.0, 25.0, 60.0, 120.0]:
            near = []
            for t in candidates:
                if which == "ymin":
                    dist = abs(t["bb"].ymin - bbox.ymin)
                else:
                    dist = abs(t["bb"].ymax - bbox.ymax)
                if dist <= tol:
                    near.append(t)
            if near:
                best = max(near, key=lambda d: d["area"])
                print(f"Picked {which} face with tol={tol}mm: area={best['area']:.2f}, face_ybb=({best['bb'].ymin:.2f},{best['bb'].ymax:.2f})")
                return best
        # Fallback to largest planar +/-Y face
        best = max(candidates, key=lambda d: d["area"])
        print(f"Fallback pick (largest planar +/-Y): area={best['area']:.2f}")
        return best

    # Heuristic: rear is typically at ymin in this dataset
    chosen = pick_at_extreme("ymin")

    rear_face = chosen["face"]
    rear_ctr = chosen["ctr"]
    rear_n = chosen["n"]

    # Ensure the cut normal points INTO the model (toward bbox center)
    v_to_center = cq.Vector(c_model.x - rear_ctr.x, c_model.y - rear_ctr.y, c_model.z - rear_ctr.z)
    n_in = rear_n
    if n_in.dot(v_to_center) < 0:
        n_in = n_in.multiply(-1)

    print(f"Chosen rear face: center=({rear_ctr.x:.2f},{rear_ctr.y:.2f},{rear_ctr.z:.2f})")
    print(f"Using cut normal (into model): ({n_in.x:.3f},{n_in.y:.3f},{n_in.z:.3f})")

    # Compute opening placement using rear face width (more stable than overall bbox, which is skewed by wand)
    rear_bb = rear_face.BoundingBox()
    panel_width = rear_bb.xlen
    x_center = (rear_bb.xmin + rear_bb.xmax) / 2.0

    side_margin = (panel_width - W) / 2.0
    if side_margin < 0:
        side_margin = 0.0
    bottom_margin = side_margin

    # Z placement: bottom margin from overall device bottom, but clamp to rear face Z span
    z_center = bbox.zmin + bottom_margin + H / 2.0

    z_min_allowed = max(bbox.zmin + H / 2.0 + 1.0, rear_bb.zmin + H / 2.0 + 1.0)
    z_max_allowed = min(bbox.zmax - H / 2.0 - 1.0, rear_bb.zmax - H / 2.0 - 1.0)
    if z_center < z_min_allowed:
        z_center = z_min_allowed
    if z_center > z_max_allowed:
        z_center = z_max_allowed

    print(f"Rear face x-span: [{rear_bb.xmin:.2f}, {rear_bb.xmax:.2f}] (width={panel_width:.2f})")
    print(f"Computed margins: side_margin={side_margin:.2f} bottom_margin={bottom_margin:.2f}")
    print(f"Opening center target: x={x_center:.2f}, z={z_center:.2f}")

    # Build sketch plane on rear face (origin set to desired opening center)
    x_dir = cq.Vector(1, 0, 0)
    if abs(n_in.dot(x_dir)) > 0.95:
        x_dir = cq.Vector(0, 0, 1)

    origin = cq.Vector(x_center, rear_ctr.y, z_center)
    plane = cq.Plane(origin=origin, normal=n_in, xDir=x_dir)

    # Cutter: rounded rectangle extruded inward by DEPTH
    cutter = (
        cq.Workplane(plane)
        .rect(W, H)
        .vertices()
        .fillet(R)
        .extrude(DEPTH)
    )

    result = model.cut(cutter)
    print("Applied rear opening cut (rounded-rectangle, 200x100, depth 30, R10).")
    return result
