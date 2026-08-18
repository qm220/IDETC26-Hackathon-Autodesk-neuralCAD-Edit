def my_cad_function(args):
    import os
    import cadquery as cq

    # OCC/OCP for prism extrusion of an existing face
    from OCP.gp import gp_Vec
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism

    in_path = os.path.expanduser(args.get("input_file", ""))
    if not in_path or not os.path.exists(in_path):
        raise ValueError(f"Input STEP file not found: {in_path}")

    wp_in = cq.importers.importStep(in_path)
    shp = wp_in.val() if hasattr(wp_in, "val") else wp_in

    if not shp.isValid():
        print("WARNING: input shape reports invalid")

    faces = shp.Faces()
    print(f"Loaded shape. Faces: {len(faces)}")

    def vnorm(v: cq.Vector) -> cq.Vector:
        l = v.Length
        if l < 1e-9:
            return cq.Vector(0, 0, 0)
        return v.multiply(1.0 / l)

    def face_normal(f: cq.Face) -> cq.Vector:
        # Planar faces have constant normal; normalAt() without args works in CQ
        try:
            n = f.normalAt()
        except TypeError:
            # Fallback: try center params
            n = f.normalAt(0, 0)
        return vnorm(n)

    def find_opposite_face(front_face: cq.Face, candidates, n_front: cq.Vector):
        c0 = front_face.Center()
        best = None
        best_dist = -1.0
        for f in candidates:
            if f is front_face:
                continue
            if f.geomType() != "PLANE":
                continue
            n = face_normal(f)
            if abs(n.dot(n_front)) < 0.98:
                continue
            # Need opposite normal
            if n.dot(n_front) > -0.98:
                continue
            dist = abs((f.Center() - c0).dot(n_front))
            if dist > best_dist:
                best = f
                best_dist = dist
        return best, best_dist

    # Prefer the two large opposing planar faces that have an inner loop (opening)
    planar_with_hole = [f for f in faces if f.geomType() == "PLANE" and len(f.Wires()) >= 2]
    planar_all = [f for f in faces if f.geomType() == "PLANE"]

    print(f"Planar faces: {len(planar_all)}; planar faces with >=2 wires: {len(planar_with_hole)}")

    def pick_front_back():
        # First attempt: use planar faces with holes
        pool = planar_with_hole if len(planar_with_hole) >= 2 else planar_all
        pool = sorted(pool, key=lambda ff: ff.Area(), reverse=True)

        if len(pool) < 2:
            raise ValueError("Could not find enough planar faces to determine thickness direction")

        f0 = pool[0]
        n0 = face_normal(f0)
        f1, dist = find_opposite_face(f0, pool[1:], n0)
        if f1 is None:
            # Fallback brute: among all planar faces pick the pair with largest separation and large areas
            best_pair = None
            best_score = -1.0
            for i in range(min(len(planar_all), 50)):
                for j in range(i + 1, min(len(planar_all), 50)):
                    a = planar_all[i]
                    b = planar_all[j]
                    na = face_normal(a)
                    nb = face_normal(b)
                    if na.dot(nb) > -0.98:
                        continue
                    d = abs((b.Center() - a.Center()).dot(na))
                    score = d * (a.Area() + b.Area())
                    if score > best_score:
                        best_score = score
                        best_pair = (a, b, na, d)
            if best_pair is None:
                raise ValueError("Failed to find opposite planar face pair")
            a, b, na, d = best_pair
            return a, b, na, d

        return f0, f1, n0, dist

    front_face_guess, back_face_guess, n_guess, thickness = pick_front_back()

    c0 = front_face_guess.Center()
    c1 = back_face_guess.Center()

    # Ensure n points from front->back by projection
    if (c1 - c0).dot(n_guess) < 0:
        # swap and flip
        front_face_guess, back_face_guess = back_face_guess, front_face_guess
        c0, c1 = c1, c0
        n_guess = n_guess.multiply(-1)

    n = vnorm(n_guess)
    thickness = abs((c1 - c0).dot(n))

    print("Chosen opposing faces:")
    print(f"  front area={front_face_guess.Area():.3f}, center={tuple(front_face_guess.Center().toTuple())}")
    print(f"  back  area={back_face_guess.Area():.3f}, center={tuple(back_face_guess.Center().toTuple())}")
    print(f"  thickness (front->back) = {thickness:.6f} mm")
    print(f"  direction n = {tuple(n.toTuple())}")

    delta = 5.0  # mm (0.5 cm)

    # Split at mid-plane between the two large faces
    mid_pt = c0 + n.multiply(thickness * 0.5)
    split_plane = cq.Plane(origin=mid_pt, normal=n)

    # Split into two solids
    pos_wp = cq.Workplane(split_plane).add(shp).split(keepTop=True)
    neg_wp = cq.Workplane(split_plane).add(shp).split(keepBottom=True)

    pos = pos_wp.val()
    neg = neg_wp.val()

    # Decide which half is front (lower projection along n)
    pos_proj = pos.BoundingBox().center.dot(n)
    neg_proj = neg.BoundingBox().center.dot(n)

    if pos_proj > neg_proj:
        back_part = pos
        front_part = neg
    else:
        back_part = neg
        front_part = pos

    print(f"Split solids bbox-center projections along n: pos={pos_proj:.6f}, neg={neg_proj:.6f}")

    # Find the split face on the front_part (planar, near mid_pt, normal parallel to n)
    def find_split_face(solid: cq.Shape, plane_point: cq.Vector, plane_normal: cq.Vector):
        best = None
        best_dist = 1e99
        for f in solid.Faces():
            if f.geomType() != "PLANE":
                continue
            fn = face_normal(f)
            if abs(abs(fn.dot(plane_normal)) - 1.0) > 1e-2:
                continue
            dist = abs((f.Center() - plane_point).dot(plane_normal))
            if dist < best_dist:
                best_dist = dist
                best = f
        return best, best_dist

    split_face, dist_to_mid = find_split_face(front_part, mid_pt, n)
    if split_face is None or dist_to_mid > 1e-2:
        print(f"WARNING: Could not confidently identify split face (dist={dist_to_mid})")

    # Extrude the split face by +5mm along n to form the bridge material
    vec = n.multiply(delta)
    prism_shape = BRepPrimAPI_MakePrism(split_face.wrapped, gp_Vec(vec.x, vec.y, vec.z), True).Shape()
    bridge = cq.Shape.cast(prism_shape)

    # Translate the back half outward by +5mm
    back_moved = back_part.translate((vec.x, vec.y, vec.z))

    # Fuse all three into one solid
    result = cq.Workplane("XY").newObject([front_part]).union(bridge).union(back_moved)

    # Debug: new thickness check via bbox projection
    bb = result.val().BoundingBox()
    # approximate thickness along n using bbox corners projections
    corners = [
        cq.Vector(bb.xmin, bb.ymin, bb.zmin), cq.Vector(bb.xmin, bb.ymin, bb.zmax),
        cq.Vector(bb.xmin, bb.ymax, bb.zmin), cq.Vector(bb.xmin, bb.ymax, bb.zmax),
        cq.Vector(bb.xmax, bb.ymin, bb.zmin), cq.Vector(bb.xmax, bb.ymin, bb.zmax),
        cq.Vector(bb.xmax, bb.ymax, bb.zmin), cq.Vector(bb.xmax, bb.ymax, bb.zmax),
    ]
    projs = [c.dot(n) for c in corners]
    approx_th = max(projs) - min(projs)
    print(f"Approx. overall extent along thickness direction after edit: {approx_th:.6f} mm (should be ~{thickness + delta:.6f} mm)")

    return result
