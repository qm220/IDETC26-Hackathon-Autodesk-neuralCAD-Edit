def my_cad_function(args):
    import cadquery as cq
    import os, math

    input_file = os.path.expanduser(args.get("input_file", ""))
    shape_wp = cq.importers.importStep(input_file)

    # Normalize to a Workplane holding a single top-level shape
    if isinstance(shape_wp, cq.Workplane):
        top_shape = shape_wp.val()
        wp_all = cq.Workplane("XY").newObject([top_shape])
    else:
        top_shape = shape_wp
        wp_all = cq.Workplane("XY").newObject([top_shape])

    top_bb = top_shape.BoundingBox()
    top_center = top_bb.center
    top_height = max(top_bb.zlen, 1e-6)

    solids = wp_all.solids().vals()
    print(f"Loaded STEP. Solids found: {len(solids)}")
    print(f"Overall bbox (x,y,z) lens: ({top_bb.xlen:.2f}, {top_bb.ylen:.2f}, {top_bb.zlen:.2f})")

    if not solids:
        print("No solids found; returning original shape")
        return wp_all

    # Heuristic: find a slender 'rod/lever-like' solid near the top of the assembly
    candidates = []
    for i, s in enumerate(solids):
        bb = s.BoundingBox()
        dx, dy, dz = bb.xlen, bb.ylen, bb.zlen
        dims = [dx, dy, dz]
        max_dim = max(dims)
        min_dim = max(min(dims), 1e-6)
        slender = max_dim / min_dim
        vol = s.Volume()
        cz_norm = (bb.center.z - top_bb.zmin) / top_height

        # basic filters: needs to be reasonably long and slender
        if max_dim < 25:
            continue
        if slender < 3.0:
            continue

        # Score: prefer slender + near top
        score = slender + 2.0 * cz_norm
        candidates.append((score, i, s, bb, slender, vol))

    if not candidates:
        # fallback: pick the most slender solid overall
        best = None
        for i, s in enumerate(solids):
            bb = s.BoundingBox()
            dims = [bb.xlen, bb.ylen, bb.zlen]
            max_dim = max(dims)
            min_dim = max(min(dims), 1e-6)
            slender = max_dim / min_dim
            if best is None or slender > best[0]:
                best = (slender, i, s, bb)
        if best is None:
            print("No suitable solid candidate; returning original shape")
            return wp_all
        _, lever_idx, lever_solid, lever_bb = best
        print(f"Fallback lever candidate idx={lever_idx}, bbox lens=({lever_bb.xlen:.2f},{lever_bb.ylen:.2f},{lever_bb.zlen:.2f})")
    else:
        candidates.sort(key=lambda t: t[0], reverse=True)
        score, lever_idx, lever_solid, lever_bb, slender, vol = candidates[0]
        print(
            f"Lever candidate idx={lever_idx}, score={score:.3f}, slender={slender:.3f}, vol={vol:.1f}, "
            f"bbox lens=({lever_bb.xlen:.2f},{lever_bb.ylen:.2f},{lever_bb.zlen:.2f})"
        )

    # Determine principal axis of the lever solid by bbox
    dx, dy, dz = lever_bb.xlen, lever_bb.ylen, lever_bb.zlen
    dims = [dx, dy, dz]
    axis_i = max(range(3), key=lambda k: dims[k])
    axis_name = ['X', 'Y', 'Z'][axis_i]

    # Decide which end to extend: the end farther from overall center along that axis
    if axis_name == 'X':
        minc, maxc, c0 = lever_bb.xmin, lever_bb.xmax, top_center.x
        axis_vec = cq.Vector(1, 0, 0)
    elif axis_name == 'Y':
        minc, maxc, c0 = lever_bb.ymin, lever_bb.ymax, top_center.y
        axis_vec = cq.Vector(0, 1, 0)
    else:
        minc, maxc, c0 = lever_bb.zmin, lever_bb.zmax, top_center.z
        axis_vec = cq.Vector(0, 0, 1)

    dmin = abs(minc - c0)
    dmax = abs(maxc - c0)
    extend_max_end = dmax >= dmin
    sel = (">" if extend_max_end else "<") + axis_name
    dir_vec = axis_vec if extend_max_end else axis_vec.multiply(-1)

    print(f"Lever principal axis: {axis_name}, extending end selector: {sel}, dir={dir_vec.toTuple()}")

    # Find a planar end-cap face at that extreme and estimate radius
    lever_wp = cq.Workplane("XY").newObject([lever_solid])
    faces_extreme = lever_wp.faces(sel).vals()
    if not faces_extreme:
        print("No extreme faces found on lever candidate; returning original shape")
        return wp_all

    planar_faces = [f for f in faces_extreme if getattr(f, 'geomType', lambda: "")() == "PLANE"]
    use_faces = planar_faces if planar_faces else faces_extreme

    # Pick the largest area face at the extreme
    cap_face = max(use_faces, key=lambda f: f.Area())
    cap_center = cap_face.Center()

    face_bb = cap_face.BoundingBox()
    # radius estimate: use area if likely circular; fallback to bbox-derived
    area = cap_face.Area()
    r_area = math.sqrt(max(area, 0.0) / math.pi) if area > 0 else 0.0
    r_bb = 0.25 * (max(face_bb.xlen, face_bb.ylen, face_bb.zlen) + min(face_bb.xlen, face_bb.ylen, face_bb.zlen))
    # choose the more plausible one
    radius = r_area if (r_area > 0 and r_area < 200) else r_bb
    radius = max(radius, 0.5)

    ext_len = 50.0  # mm (5 cm)
    print(f"Cap face area={area:.3f}, r_area={r_area:.3f}, r_bb={r_bb:.3f} -> using radius={radius:.3f}, ext_len={ext_len}")
    print(f"Cap center: ({cap_center.x:.3f}, {cap_center.y:.3f}, {cap_center.z:.3f})")

    # Create extension cylinder and union to full assembly
    ext_cyl = cq.Solid.makeCylinder(radius, ext_len, cap_center, dir_vec)
    result = wp_all.union(ext_cyl)

    return result
