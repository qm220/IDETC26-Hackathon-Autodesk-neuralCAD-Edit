def my_cad_function(args):
    import cadquery as cq
    import os

    input_file = args.get("input_file", None)
    if not input_file:
        raise ValueError("args['input_file'] is required")
    input_file = os.path.expanduser(input_file)
    if not os.path.exists(input_file):
        raise ValueError(f"Missing STEP file: {input_file}")

    wp = cq.importers.importStep(input_file)
    solid = wp.val() if hasattr(wp, "val") else wp

    bb = solid.BoundingBox()
    dx, dy, dz = (bb.xmax - bb.xmin), (bb.ymax - bb.ymin), (bb.zmax - bb.zmin)
    max_dim = max(dx, dy, dz)

    print("=== Loaded model ===")
    print(f"BBox: x[{bb.xmin:.6f},{bb.xmax:.6f}] y[{bb.ymin:.6f},{bb.ymax:.6f}] z[{bb.zmin:.6f},{bb.zmax:.6f}]")
    print(f"Dims: dx={dx:.6f}, dy={dy:.6f}, dz={dz:.6f}, max_dim={max_dim:.6f}")

    # -----------------------------
    # Find underside pocket shelf/floor face:
    # planar face with normal ~ +/-Y, not the global bottom, low-ish Y, large area.
    # -----------------------------
    bottom_y = bb.ymin

    planars = []
    for f in solid.Faces():
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
            # focus in the lower region of part to find underside pocket shelf
            if c.y > bottom_y + 0.40 * dy:
                continue
            # also exclude tiny faces
            a = f.Area()
            if a < 0.01 * dx * dz:
                continue
            planars.append((a, c.y, f, n, c))
        except Exception:
            continue

    if not planars:
        raise ValueError("Could not find a suitable planar underside pocket floor/shelf face.")

    # Prefer the largest-area candidate in the lower region
    planars.sort(key=lambda t: (-t[0], t[1]))
    floor_area, floor_y, floor_face, floor_n, floor_c = planars[0]
    floor_bb = floor_face.BoundingBox()

    print("=== Chosen pocket floor/shelf face ===")
    print(f"floor_y={floor_y:.6f} area={floor_area:.6f} center=({floor_c.x:.6f},{floor_c.y:.6f},{floor_c.z:.6f})")
    print(f"floor_face_bb: x[{floor_bb.xmin:.6f},{floor_bb.xmax:.6f}] z[{floor_bb.zmin:.6f},{floor_bb.zmax:.6f}]")

    # -----------------------------
    # Unit heuristic
    # (previous run inferred inches; keep same logic but simpler & stable)
    # -----------------------------
    # If the part is ~13 units long, it's very likely inches for a bracket.
    # Use inches unless the model is clearly in mm.
    if max_dim > 100:  # clearly mm
        mm_to_model = 1.0
        inferred = "mm"
    else:
        mm_to_model = 1.0 / 25.4
        inferred = "inch"

    rib_t = 1.5 * mm_to_model
    clearance = 0.5 * mm_to_model        # keep rib off any exterior opening
    eps_overlap = 0.05 * mm_to_model     # small overlap into existing solid for robust fuse

    print("=== Units ===")
    print(f"inferred_units='{inferred}', mm_to_model={mm_to_model:.8f}")
    print(f"rib_thickness(model)={rib_t:.6f}, clearance(model)={clearance:.6f}, eps_overlap(model)={eps_overlap:.6f}")

    # -----------------------------
    # Determine which side of the floor face is void (pocket)
    # by sampling inside-test slightly off the face.
    # -----------------------------
    # choose a small step relative to estimated pocket depth
    pocket_depth_guess = max(1e-9, floor_y - bottom_y)
    step = min(0.40 * pocket_depth_guess, 0.04 * dy)
    step = max(step, 2.0 * eps_overlap)

    def is_inside(vec):
        try:
            return bool(solid.isInside(vec, 1e-6 * max_dim))
        except Exception:
            # fallback: if isInside isn't available, assume underside pocket is toward -Y
            return True

    p0 = cq.Vector(floor_c.x, floor_y, floor_c.z)
    p_plus = cq.Vector(floor_c.x, floor_y + step, floor_c.z)
    p_minus = cq.Vector(floor_c.x, floor_y - step, floor_c.z)

    inside_plus = is_inside(p_plus)
    inside_minus = is_inside(p_minus)

    # void direction is where the point is NOT inside the solid
    if (not inside_minus) and inside_plus:
        void_dir = cq.Vector(0, -1, 0)
        void_dir_label = "-Y"
    elif (not inside_plus) and inside_minus:
        void_dir = cq.Vector(0, 1, 0)
        void_dir_label = "+Y"
    else:
        # ambiguous: default to underside pocket direction (-Y)
        void_dir = cq.Vector(0, -1, 0)
        void_dir_label = "-Y (default/ambiguous)"

    print("=== Void side detection ===")
    print(f"step={step:.6f} inside_plus={inside_plus} inside_minus={inside_minus} -> void_dir={void_dir_label}")

    # -----------------------------
    # Rib footprint (along X) centered in the pocket floor
    # -----------------------------
    xspan = max(1e-9, (floor_bb.xmax - floor_bb.xmin))
    zspan = max(1e-9, (floor_bb.zmax - floor_bb.zmin))

    # keep away from pocket transitions near ends
    x_margin = max(0.08 * xspan, 10.0 * rib_t)
    L = max(0.0, xspan - 2.0 * x_margin)
    if L < 25.0 * rib_t:
        L = max(25.0 * rib_t, 0.65 * xspan)

    # keep rib within pocket width in Z as well
    # (rib width is rib_t; ensure we are not too close to side walls by verifying zspan)
    if zspan < 6.0 * rib_t:
        # pocket too narrow for the requested rib thickness; reduce slightly but keep intent
        rib_w = max(0.6 * rib_t, 0.15 * zspan)
    else:
        rib_w = rib_t

    print("=== Rib footprint ===")
    print(f"xspan={xspan:.6f}, zspan={zspan:.6f}, x_margin={x_margin:.6f}, L={L:.6f}, rib_w={rib_w:.6f}")

    # -----------------------------
    # Rib depth: grow into the pocket void but stop short of any exterior opening.
    # For underside pocket (void_dir=-Y), use the distance to global bottom plane.
    # -----------------------------
    if void_dir.y < 0:
        max_depth = max(0.0, (floor_y - bottom_y) - clearance)
        depth = max_depth
    else:
        # if pocket void is above the floor, limit depth to avoid breaking out
        max_depth = max(0.0, (bb.ymax - floor_y) - clearance)
        depth = 0.35 * max_depth

    # ensure non-trivial depth
    depth = max(depth, 8.0 * rib_t)
    # never exceed available depth
    depth = min(depth, max_depth if max_depth > 0 else depth)

    print("=== Rib depth ===")
    print(f"pocket_depth_guess={pocket_depth_guess:.6f}, max_depth={max_depth:.6f}, chosen_depth={depth:.6f}")

    if depth <= 1e-9:
        raise ValueError("Computed rib depth is ~0; cannot place rib without breaking exterior or missing pocket.")

    # -----------------------------
    # Build rib prism: sketch on a plane parallel to the floor, offset slightly into SOLID
    # (opposite void direction) so the union fuses robustly.
    # Plane axes: xDir = +X, plane-y axis becomes +Z (since normal is +/-Y).
    # -----------------------------
    origin_y = float(floor_y - void_dir.y * eps_overlap)  # shift into solid side
    plane = cq.Plane(origin=(0.0, origin_y, 0.0), xDir=(1, 0, 0), normal=(0.0, float(void_dir.y), 0.0))

    rib = (
        cq.Workplane(plane)
        .center(float(floor_c.x), float(floor_c.z))
        .rect(float(L), float(rib_w), centered=True)
        .extrude(float(depth + eps_overlap))
    ).val()

    V0 = solid.Volume()
    Vrib = rib.Volume()
    print("=== Volumes ===")
    print(f"V0={V0:.6f}, Vrib={Vrib:.6f}")

    # Fuse
    result = solid.union(rib)

    # -----------------------------
    # Sanity checks: should add material and not change external bbox extents.
    # -----------------------------
    bb2 = result.BoundingBox()
    V2 = result.Volume()
    dV = V2 - V0

    print("=== Result checks ===")
    print(f"V2={V2:.6f}, dV={dV:.6f}")
    print(
        "bbox_delta="
        f"dxmin={bb2.xmin - bb.xmin:.6g}, dxmax={bb2.xmax - bb.xmax:.6g}, "
        f"dymin={bb2.ymin - bb.ymin:.6g}, dymax={bb2.ymax - bb.ymax:.6g}, "
        f"dzmin={bb2.zmin - bb.zmin:.6g}, dzmax={bb2.zmax - bb.zmax:.6g}"
    )

    if dV <= 1e-9:
        raise ValueError("Union did not increase volume; rib likely failed to fuse or was degenerate.")

    # Do not allow outward bbox growth (external breakthrough). Tiny tolerances allowed.
    tol = 1e-7 * max_dim
    if (bb2.xmin < bb.xmin - tol) or (bb2.xmax > bb.xmax + tol) or (bb2.ymin < bb.ymin - tol) or (bb2.ymax > bb.ymax + tol) or (bb2.zmin < bb.zmin - tol) or (bb2.zmax > bb.zmax + tol):
        raise ValueError("Rib appears to have broken through the exterior (bounding box changed).")

    # Ensure we're returning a single fused solid if possible
    try:
        nsol = len(result.Solids())
        print(f"n_solids={nsol}")
        if nsol > 1:
            # Attempt to consolidate by taking the largest solid
            sols = result.Solids()
            best = max(sols, key=lambda s: s.Volume())
            result = best
            print("WARNING: union produced multiple solids; returning largest solid.")
    except Exception:
        pass

    return result
