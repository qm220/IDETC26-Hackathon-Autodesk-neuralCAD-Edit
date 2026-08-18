def my_cad_function(args):
    import os
    import cadquery as cq

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
    planar = [f for f in faces if f.geomType() == "PLANE"]
    print(f"Loaded shape. Faces: {len(faces)} | Planar faces: {len(planar)}")

    def vnorm(v: cq.Vector) -> cq.Vector:
        L = v.Length
        if L < 1e-12:
            return cq.Vector(0, 0, 0)
        return v.multiply(1.0 / L)

    def face_normal(f: cq.Face) -> cq.Vector:
        try:
            n = f.normalAt()
        except TypeError:
            n = f.normalAt(0, 0)
        return vnorm(n)

    # --- Identify the two opposing "cap" faces (front/back) ---
    planar_with_hole = [f for f in planar if len(f.Wires()) >= 2]
    print(f"Planar faces with >=2 wires (likely cap faces with opening): {len(planar_with_hole)}")

    def pick_cap_pair(cands):
        # Return (fa, fb) best opposing pair
        if len(cands) < 2:
            return None
        info = []
        for f in cands:
            info.append((f, f.Area(), f.Center(), face_normal(f), len(f.Wires())))

        best = None
        best_score = -1e99
        for i in range(len(info)):
            fi, ai, ci, ni, wi = info[i]
            for j in range(i + 1, len(info)):
                fj, aj, cj, nj, wj = info[j]
                dot = ni.dot(nj)
                if dot > -0.985:  # not sufficiently opposite
                    continue
                # distance between planes measured along ni
                sep = abs((cj - ci).dot(ni))
                # encourage similar area (avoid pairing a small rim face with a huge face)
                ar = min(ai, aj) / max(ai, aj)
                score = sep * (ar ** 2) * (ai + aj)
                if score > best_score:
                    best_score = score
                    best = (fi, fj)
        return best

    # Prefer faces with holes; otherwise fallback to all planar faces
    cap_pair = pick_cap_pair(planar_with_hole)
    if cap_pair is None:
        print("Fallback: could not find opposing pair among faces-with-holes; trying all planar faces")
        cap_pair = pick_cap_pair(planar)

    if cap_pair is None:
        raise ValueError("Failed to identify opposing planar cap faces to define thickness direction")

    fa, fb = cap_pair
    na = face_normal(fa)
    ca = fa.Center()
    cb = fb.Center()

    # Define thickness direction n from front->back using fa's normal
    s = (cb - ca).dot(na)
    if abs(s) < 1e-9:
        # fallback: use center-to-center direction
        n = vnorm(cb - ca)
        print("WARNING: ambiguous cap ordering; using center-to-center direction for n")
        # define front/back by projection
        if (cb - ca).dot(n) < 0:
            fa, fb = fb, fa
            ca, cb = cb, ca
    else:
        if s > 0:
            front_face, back_face = fa, fb
            n = na
        else:
            front_face, back_face = fb, fa
            n = na.multiply(-1)
            ca, cb = cb, ca

    n = vnorm(n)

    # Thickness estimate using face centers along n (plane separation)
    thickness_center = abs((cb - ca).dot(n))

    def extent_along_n(shape: cq.Shape, nvec: cq.Vector):
        vs = shape.Vertices()
        if not vs:
            return None
        projs = [v.Center().dot(nvec) for v in vs]
        return (min(projs), max(projs), max(projs) - min(projs))

    ext0 = extent_along_n(shp, n)

    print("Chosen opposing cap faces:")
    print(f"  front: area={front_face.Area():.3f}, wires={len(front_face.Wires())}, center={tuple(front_face.Center().toTuple())}")
    print(f"  back : area={back_face.Area():.3f}, wires={len(back_face.Wires())}, center={tuple(back_face.Center().toTuple())}")
    print(f"  n (front->back) = {tuple(n.toTuple())}")
    print(f"  thickness (by centers along n) = {thickness_center:.6f} mm")
    if ext0:
        print(f"  extent along n (by vertex projections) = {ext0[2]:.6f} mm")

    # --- Apply requested edit: make taller by +5mm, preserve area profile ---
    delta = 5.0  # mm
    vec = n.multiply(delta)

    # Extrude the back cap face outward by +delta along n and union it.
    # This keeps the in-plane profile identical and extends only in thickness direction.
    prism = BRepPrimAPI_MakePrism(back_face.wrapped, gp_Vec(vec.x, vec.y, vec.z), True).Shape()
    prism_cq = cq.Shape.cast(prism)

    result = cq.Workplane("XY").newObject([shp]).union(prism_cq)

    # Debug check: new extent along n
    ext1 = extent_along_n(result.val(), n)
    if ext1 and ext0:
        print(f"New extent along n (by vertex projections) = {ext1[2]:.6f} mm")
        print(f"Delta extent along n = {(ext1[2] - ext0[2]):.6f} mm (target: {delta:.6f} mm)")

    return result
