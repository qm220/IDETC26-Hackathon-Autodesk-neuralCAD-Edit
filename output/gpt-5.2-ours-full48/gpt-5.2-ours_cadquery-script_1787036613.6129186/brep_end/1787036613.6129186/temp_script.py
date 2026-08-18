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

    def extent_along_n(shape: cq.Shape, nvec: cq.Vector):
        vs = shape.Vertices()
        if not vs:
            return None
        projs = [v.Center().dot(nvec) for v in vs]
        return (min(projs), max(projs), max(projs) - min(projs))

    # --- Choose thickness direction n ---
    # Strategy: evaluate a few dominant planar-face normals; pick the one that
    # yields (large total planar area with that orientation) / (small overall extent).
    if len(planar) < 2:
        raise ValueError("Not enough planar faces to infer thickness direction")

    # Sort planar faces by area, take top-N as candidates
    planar_info = [(f, f.Area(), face_normal(f)) for f in planar]
    planar_info.sort(key=lambda t: t[1], reverse=True)

    cand_normals = []
    for f, a, n in planar_info[:20]:
        if n.Length < 1e-9:
            continue
        # de-duplicate by direction (treat +/- as same)
        keep = True
        for nn in cand_normals:
            if abs(nn.dot(n)) > 0.995:
                keep = False
                break
        if keep:
            cand_normals.append(n)

    if not cand_normals:
        raise ValueError("Failed to derive any candidate normals")

    # Evaluate candidates
    best = None
    best_score = -1e99
    for n in cand_normals:
        ext = extent_along_n(shp, n)
        if not ext:
            continue
        extent_len = ext[2]
        # total planar area that is near-parallel to this normal
        area_sum = 0.0
        count = 0
        for f, a, fn in planar_info:
            if abs(fn.dot(n)) > 0.985:
                area_sum += a
                count += 1
        # score: favor large area and small extent
        score = area_sum / max(extent_len, 1e-6)
        # Also require at least two faces in this orientation (to be a thickness-like direction)
        if count >= 2 and score > best_score:
            best_score = score
            best = (n, extent_len, area_sum, count)

    if best is None:
        # fallback: just use largest planar face normal
        n = planar_info[0][2]
        ext = extent_along_n(shp, n)
        print("WARNING: could not robustly score a thickness direction; using largest planar-face normal")
        if not ext:
            raise ValueError("Failed to compute extents along fallback normal")
    else:
        n = best[0]
        ext = extent_along_n(shp, n)

    n = vnorm(n)
    pmin, pmax, t0 = ext
    print(f"Chosen thickness direction n = {tuple(n.toTuple())}")
    print(f"Initial extent along n (by vertex projections) = {t0:.6f} mm")

    # --- Identify planar faces on the 'back' extreme (max projection along n) ---
    # Collect planar faces whose normals are aligned with +n and whose center lies at the max plane.
    # Use center projections to find the extreme plane location among aligned faces.
    aligned_plus = []
    for f, a, fn in planar_info:
        d = fn.dot(n)
        if d > 0.985:  # aligned with +n
            aligned_plus.append((f, a, fn, f.Center().dot(n)))

    if not aligned_plus:
        # If orientations are flipped, use faces aligned with -n but still at max projection
        aligned_minus = []
        for f, a, fn in planar_info:
            d = fn.dot(n)
            if d < -0.985:
                aligned_minus.append((f, a, fn, f.Center().dot(n)))
        if not aligned_minus:
            raise ValueError("Failed to find planar faces aligned with +/- thickness direction")
        # Choose max plane among these too
        cmax = max(ci for _, _, _, ci in aligned_minus)
        back_faces = [f for f, a, fn, ci in aligned_minus if abs(ci - cmax) < 0.25]
        print("NOTE: using faces aligned with -n at the back extreme; will still extrude along +n")
    else:
        cmax = max(ci for _, _, _, ci in aligned_plus)
        back_faces = [f for f, a, fn, ci in aligned_plus if abs(ci - cmax) < 0.25]

    print(f"Back extreme plane (center-projection) cmax = {cmax:.6f}")
    print(f"Back cap faces selected for extension: {len(back_faces)}")
    for i, f in enumerate(back_faces[:10]):
        print(f"  back_face[{i}]: area={f.Area():.3f}, wires={len(f.Wires())}, center={tuple(f.Center().toTuple())}")

    # --- Apply requested edit: make taller by +5mm, preserve in-plane profile ---
    delta = 5.0  # mm
    vec = n.multiply(delta)

    prisms = []
    for f in back_faces:
        pr = BRepPrimAPI_MakePrism(f.wrapped, gp_Vec(vec.x, vec.y, vec.z), True).Shape()
        prisms.append(cq.Shape.cast(pr))

    result = cq.Workplane("XY").newObject([shp])
    for pr in prisms:
        result = result.union(pr)

    # Debug check: new extent along n
    ext1 = extent_along_n(result.val(), n)
    if ext1:
        t1 = ext1[2]
        print(f"New extent along n (by vertex projections) = {t1:.6f} mm")
        print(f"Delta extent along n = {(t1 - t0):.6f} mm (target: {delta:.6f} mm)")

    return result
