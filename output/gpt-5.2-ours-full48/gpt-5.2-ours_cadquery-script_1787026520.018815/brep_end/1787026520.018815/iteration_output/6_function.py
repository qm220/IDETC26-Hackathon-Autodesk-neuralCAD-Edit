def my_cad_function(args):
    import cadquery as cq
    import os

    input_file = args.get("input_file", None)
    if not input_file:
        raise ValueError("args['input_file'] is required")
    input_file = os.path.expanduser(input_file)
    if not os.path.exists(input_file):
        raise ValueError(f"Missing STEP file: {input_file}")

    wp_in = cq.importers.importStep(input_file)
    shape = wp_in.val() if hasattr(wp_in, "val") else wp_in

    bb = shape.BoundingBox()
    dx, dy, dz = (bb.xmax - bb.xmin), (bb.ymax - bb.ymin), (bb.zmax - bb.zmin)
    max_dim = max(dx, dy, dz)

    print("=== Loaded model ===")
    print(f"BBox: x[{bb.xmin:.6f},{bb.xmax:.6f}] y[{bb.ymin:.6f},{bb.ymax:.6f}] z[{bb.zmin:.6f},{bb.zmax:.6f}]")
    print(f"Dims: dx={dx:.6f}, dy={dy:.6f}, dz={dz:.6f}, max_dim={max_dim:.6f}")

    # -----------------------------
    # Find underside pocket floor/shelf face:
    # planar face with normal ~ +/-Y, not the global bottom, low-ish Y, large area.
    # -----------------------------
    bottom_y = bb.ymin

    planars = []
    for f in shape.Faces():
        try:
            if f.geomType() != "PLANE":
                continue
            n = f.normalAt()
            if abs(n.y) < 0.97:
                continue
            c = f.Center()
            # exclude global bottom plane
            if abs(c.y - bottom_y) < 1e-7 * max_dim:
                continue
            # focus in lower region
            if c.y > bottom_y + 0.45 * dy:
                continue
            a = f.Area()
            if a < 0.01 * dx * dz:
                continue
            planars.append((a, c.y, f, n, c))
        except Exception:
            continue

    if not planars:
        raise ValueError("Could not find a suitable planar underside pocket floor/shelf face.")

    planars.sort(key=lambda t: (-t[0], t[1]))
    floor_area, floor_y, floor_face, floor_n, floor_c = planars[0]
    floor_bb = floor_face.BoundingBox()

    print("=== Chosen pocket floor/shelf face ===")
    print(f"floor_y={floor_y:.6f} area={floor_area:.6f} center=({floor_c.x:.6f},{floor_c.y:.6f},{floor_c.z:.6f})")
    print(f"floor_face_bb: x[{floor_bb.xmin:.6f},{floor_bb.xmax:.6f}] z[{floor_bb.zmin:.6f},{floor_bb.zmax:.6f}]")

    # -----------------------------
    # Unit heuristic
    # -----------------------------
    if max_dim > 100.0:
        mm_to_model = 1.0
        inferred = "mm"
    else:
        mm_to_model = 1.0 / 25.4
        inferred = "inch"

    rib_t = 1.5 * mm_to_model
    clearance = 0.5 * mm_to_model        # keep rib off exterior bottom plane
    eps_overlap = 0.05 * mm_to_model     # overlap into solid for robust fuse

    print("=== Units ===")
    print(f"inferred_units='{inferred}', mm_to_model={mm_to_model:.8f}")
    print(f"rib_thickness(model)={rib_t:.6f}, clearance(model)={clearance:.6f}, eps_overlap(model)={eps_overlap:.6f}")

    # -----------------------------
    # Determine void side of the floor face (pocket is typically toward -Y)
    # by sampling isInside slightly off the face.
    # -----------------------------
    pocket_depth_guess = max(1e-9, floor_y - bottom_y)
    step = min(0.40 * pocket_depth_guess, 0.04 * dy)
    step = max(step, 2.0 * eps_overlap)

    def is_inside(vec):
        try:
            return bool(shape.isInside(vec, 1e-6 * max_dim))
        except Exception:
            return None

    p_plus = cq.Vector(floor_c.x, floor_y + step, floor_c.z)
    p_minus = cq.Vector(floor_c.x, floor_y - step, floor_c.z)
    inside_plus = is_inside(p_plus)
    inside_minus = is_inside(p_minus)

    # void direction is where the point is NOT inside
    if inside_plus is not None and inside_minus is not None:
        if (inside_plus is True) and (inside_minus is False):
            void_dir = cq.Vector(0, -1, 0)
            void_dir_label = "-Y"
        elif (inside_plus is False) and (inside_minus is True):
            void_dir = cq.Vector(0, 1, 0)
            void_dir_label = "+Y"
        else:
            void_dir = cq.Vector(0, -1, 0)
            void_dir_label = "-Y (default/ambiguous)"
    else:
        void_dir = cq.Vector(0, -1, 0)
        void_dir_label = "-Y (default/no-isInside)"

    print("=== Void side detection ===")
    print(f"step={step:.6f} inside_plus={inside_plus} inside_minus={inside_minus} -> void_dir={void_dir_label}")

    # -----------------------------
    # Rib footprint (longitudinal along X), centered within floor face bbox
    # -----------------------------
    xspan = max(1e-9, (floor_bb.xmax - floor_bb.xmin))
    zspan = max(1e-9, (floor_bb.zmax - floor_bb.zmin))

    x_mid = 0.5 * (floor_bb.xmin + floor_bb.xmax)
    z_mid = 0.5 * (floor_bb.zmin + floor_bb.zmax)

    x_margin = max(0.10 * xspan, 10.0 * rib_t)
    L = max(0.0, xspan - 2.0 * x_margin)
    if L < 25.0 * rib_t:
        L = max(25.0 * rib_t, 0.65 * xspan)

    rib_w = rib_t
    if zspan < 6.0 * rib_t:
        rib_w = max(0.6 * rib_t, 0.15 * zspan)

    print("=== Rib footprint ===")
    print(f"xspan={xspan:.6f}, zspan={zspan:.6f}, x_mid={x_mid:.6f}, z_mid={z_mid:.6f}, x_margin={x_margin:.6f}, L={L:.6f}, rib_w={rib_w:.6f}")

    # -----------------------------
    # Rib depth: extrude into pocket void but stop short of global bottom plane.
    # If void is toward -Y, limit by (floor_y - bottom_y) - clearance.
    # -----------------------------
    if void_dir.y < 0:
        max_depth = max(0.0, (floor_y - bottom_y) - clearance)
        depth = max_depth
    else:
        max_depth = max(0.0, (bb.ymax - floor_y) - clearance)
        depth = 0.35 * max_depth

    # ensure non-trivial depth
    depth = max(depth, 8.0 * rib_t)
    if max_depth > 0:
        depth = min(depth, max_depth)

    print("=== Rib depth ===")
    print(f"pocket_depth_guess={pocket_depth_guess:.6f}, max_depth={max_depth:.6f}, chosen_depth={depth:.6f}")

    if depth <= 1e-9:
        raise ValueError("Computed rib depth is ~0; cannot place rib without breaking exterior or missing pocket.")

    # -----------------------------
    # Build rib prism from an offset plane so it fuses robustly.
    # Use plane normal = void_dir so extrude grows into the void.
    # Offset the sketch plane slightly into solid (opposite void) for overlap.
    # -----------------------------
    origin_y = float(floor_y - void_dir.y * eps_overlap)  # shift into solid side
    plane = cq.Plane(origin=(0.0, origin_y, 0.0), xDir=(1, 0, 0), normal=(0.0, float(void_dir.y), 0.0))

    rib_shape = (
        cq.Workplane(plane)
        .center(float(x_mid), float(z_mid))
        .rect(float(L), float(rib_w), centered=True)
        .extrude(float(depth + eps_overlap))
    ).val()

    try:
        V0 = shape.Volume()
        Vrib = rib_shape.Volume()
        print("=== Volumes ===")
        print(f"V0={V0:.6f}, Vrib={Vrib:.6f}")
    except Exception:
        V0 = None

    # Fuse using Workplane.union (Shape/Solid may not have .union in this environment)
    result_wp = cq.Workplane(obj=shape).union(rib_shape)
    result = result_wp.val()

    # -----------------------------
    # Sanity checks
    # -----------------------------
    bb2 = result.BoundingBox()
    if V0 is not None:
        V2 = result.Volume()
        dV = V2 - V0
        print("=== Result checks ===")
        print(f"V2={V2:.6f}, dV={dV:.6f}")
        if dV <= 1e-9:
            raise ValueError("Union did not increase volume; rib likely failed to fuse or was degenerate.")

    print(
        "bbox_delta="
        f"dxmin={bb2.xmin - bb.xmin:.6g}, dxmax={bb2.xmax - bb.xmax:.6g}, "
        f"dymin={bb2.ymin - bb.ymin:.6g}, dymax={bb2.ymax - bb.ymax:.6g}, "
        f"dzmin={bb2.zmin - bb.zmin:.6g}, dzmax={bb2.zmax - bb.zmax:.6g}"
    )

    # Do not allow outward bbox growth (breakthrough). Tiny numerical tolerance allowed.
    tol = 1e-7 * max_dim
    if (bb2.xmin < bb.xmin - tol) or (bb2.xmax > bb.xmax + tol) or (bb2.ymin < bb.ymin - tol) or (bb2.ymax > bb.ymax + tol) or (bb2.zmin < bb.zmin - tol) or (bb2.zmax > bb.zmax + tol):
        raise ValueError("Rib appears to have broken through the exterior (bounding box changed).")

    # If union produced multiple solids, return the largest
    try:
        sols = result.Solids()
        if len(sols) > 1:
            best = max(sols, key=lambda s: s.Volume())
            print(f"WARNING: union produced {len(sols)} solids; returning largest.")
            result = best
    except Exception:
        pass

    return result
