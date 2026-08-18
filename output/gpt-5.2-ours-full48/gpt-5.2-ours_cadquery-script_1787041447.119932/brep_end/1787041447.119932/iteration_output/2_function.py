def my_cad_function(args):
    import cadquery as cq
    import os, math

    in_path = os.path.expanduser(args.get("input_file", ""))
    if not in_path or not os.path.exists(in_path):
        raise ValueError(f"Input STEP file not found: {in_path}")

    model = cq.importers.importStep(in_path)
    root = model.val() if hasattr(model, "val") else model
    solids = list(root.Solids())

    print(f"Loaded STEP: {in_path}")
    print(f"Num solids: {len(solids)}")

    # Requested fillet radius: 0.635 cm = 6.35 mm
    R = 6.35

    def bb_info(s):
        bb = s.BoundingBox()
        return bb.xlen, bb.ylen, bb.zlen, bb.center

    for i, s in enumerate(solids):
        xlen, ylen, zlen, c = bb_info(s)
        print(f"Solid[{i}] bbox: x={xlen:.3f} y={ylen:.3f} z={zlen:.3f} center=({c.x:.3f},{c.y:.3f},{c.z:.3f})")

    def gtype(obj):
        try:
            return str(obj.geomType()).upper()
        except Exception:
            return "UNKNOWN"

    def vec_dot(a, b):
        return a.x * b.x + a.y * b.y + a.z * b.z

    def vec_len(a):
        return math.sqrt(max(0.0, a.x * a.x + a.y * a.y + a.z * a.z))

    def unit(v):
        L = vec_len(v)
        if L < 1e-12:
            return None
        return cq.Vector(v.x / L, v.y / L, v.z / L)

    def face_normal_at_point(face, pnt):
        # Best-effort normal at a 3D point; fall back to face center.
        try:
            u, v = face.paramAt(pnt)
            n = face.normalAt(u, v)
            return unit(n)
        except Exception:
            try:
                n = face.normalAt(face.Center())
                return unit(n)
            except Exception:
                return None

    def dihedral_angle_deg(face1, face2, edge_center):
        n1 = face_normal_at_point(face1, edge_center)
        n2 = face_normal_at_point(face2, edge_center)
        if n1 is None or n2 is None:
            return None
        dp = max(-1.0, min(1.0, vec_dot(n1, n2)))
        return math.degrees(math.acos(dp))

    def identify_solids(solids):
        # Identify clamp (largest Y extent), vertical (largest Z of remaining), diagonal (other)
        if len(solids) < 3:
            return None, None, None
        clamp_i = max(range(len(solids)), key=lambda i: solids[i].BoundingBox().ylen)
        rem = [i for i in range(len(solids)) if i != clamp_i]
        vert_i = max(rem, key=lambda i: solids[i].BoundingBox().zlen)
        diag_i = [i for i in rem if i != vert_i][0]
        return diag_i, vert_i, clamp_i

    diag_i, vert_i, clamp_i = identify_solids(solids)
    if diag_i is None:
        print("WARNING: Expected 3 solids; returning original model")
        return model

    print(f"Identified clamp_i={clamp_i}, vertical_i={vert_i}, diagonal_i={diag_i}")

    diagonal = solids[diag_i]
    vertical = solids[vert_i]
    clamp = solids[clamp_i]

    def collect_candidate_edges(shape, want_face_types=("PLANE", "CYLINDER"), only_line=True, min_len=50.0):
        cands = []
        for e in shape.Edges():
            try:
                if only_line and "LINE" not in gtype(e):
                    continue
                L = float(e.Length())
                if L < min_len:
                    continue
                faces = list(e.ancestors(shape, kind="Face"))
                if len(faces) != 2:
                    continue
                ft = [gtype(f) for f in faces]
                # Must include the requested face types (order independent)
                if not (want_face_types[0] in ft and want_face_types[1] in ft):
                    continue
                ec = e.Center()
                ang = dihedral_angle_deg(faces[0], faces[1], ec)
                # Skip nearly-tangent edges (fillet tool often rejects)
                if ang is not None and (ang < 5.0 or ang > 175.0):
                    continue

                # Determine the PLANE face (for clustering by the "blade" planar face)
                plane_face = None
                for f in faces:
                    if gtype(f) == "PLANE":
                        plane_face = f
                        break
                if plane_face is None:
                    continue

                pn = face_normal_at_point(plane_face, plane_face.Center())
                if pn is None:
                    continue

                # Normalize normal sign for stable clustering (flip so largest abs component is positive)
                ax = [abs(pn.x), abs(pn.y), abs(pn.z)]
                kmax = ax.index(max(ax))
                comp = [pn.x, pn.y, pn.z][kmax]
                if comp < 0:
                    pn = cq.Vector(-pn.x, -pn.y, -pn.z)

                pc = plane_face.Center()
                d = pn.x * pc.x + pn.y * pc.y + pn.z * pc.z  # plane offset-ish for clustering

                cands.append({
                    "edge": e,
                    "L": L,
                    "center": (ec.x, ec.y, ec.z),
                    "face_types": ft,
                    "angle": ang,
                    "plane_key": (round(pn.x, 2), round(pn.y, 2), round(pn.z, 2), round(d, 1)),
                })
            except Exception:
                continue
        cands.sort(key=lambda t: t["L"], reverse=True)
        return cands

    def try_fillet_on_one_blade_long_edge(shape, shape_name):
        """Attempt to fillet the intended 'blade long edge' on the given shape.
        We interpret this as the long LINE edge(s) between a planar 'blade' face and an outer cylindrical face.
        Because STEP often splits edges, we may need to fillet multiple colinear segments that belong to the same plane.
        """
        cands = collect_candidate_edges(shape, want_face_types=("PLANE", "CYLINDER"), only_line=True, min_len=60.0)
        print(f"{shape_name}: plane-cylinder LINE candidates (L>=60): {len(cands)}")
        for i, c in enumerate(cands[:20]):
            angs = "None" if c["angle"] is None else f"{c['angle']:.1f}"
            print(f"  cand[{i}] L={c['L']:.3f} center=({c['center'][0]:.3f},{c['center'][1]:.3f},{c['center'][2]:.3f}) angle={angs} plane_key={c['plane_key']} faces={c['face_types']}")

        if not cands:
            return None

        # Cluster by the planar face (normal + offset). Choose the cluster with maximum total length.
        clusters = {}
        for c in cands:
            clusters.setdefault(c["plane_key"], []).append(c)

        best_key = None
        best_sum = -1.0
        for k, items in clusters.items():
            sL = sum(it["L"] for it in items)
            if sL > best_sum:
                best_sum = sL
                best_key = k

        group = clusters[best_key]
        group.sort(key=lambda t: t["L"], reverse=True)

        # Within that plane cluster, keep only the longest few segments (avoid dragging in short local features)
        maxL = group[0]["L"]
        group = [g for g in group if g["L"] >= 0.80 * maxL]

        print(f"{shape_name}: selected plane cluster {best_key} with {len(group)} edge segment(s), sumL={sum(g['L'] for g in group):.3f}")

        edges = [g["edge"] for g in group]

        # Try filleting all selected segments at once (preferred)
        try:
            new_shape = cq.Workplane(obj=shape).newObject(edges).fillet(R).val()
            print(f"{shape_name}: SUCCESS fillet R={R}mm on {len(edges)} edge segment(s) (plane-cylinder cluster)")
            return new_shape
        except Exception as e:
            print(f"{shape_name}: combined fillet failed: {e}")

        # Fallback: try sequentially adding segments
        cur = shape
        done = 0
        for idx, ed in enumerate(edges):
            try:
                cur = cq.Workplane(obj=cur).newObject([ed]).fillet(R).val()
                done += 1
                print(f"{shape_name}: sequential fillet succeeded on segment {idx}")
            except Exception as e:
                print(f"{shape_name}: sequential fillet failed on segment {idx}: {e}")

        if done > 0:
            print(f"{shape_name}: SUCCESS fillet R={R}mm on {done}/{len(edges)} segments (sequential)")
            return cur

        return None

    # First attempt: diagonal member (most likely 'blade edge' is on the long diagonal member)
    diag_mod = try_fillet_on_one_blade_long_edge(diagonal, "diagonal")
    if diag_mod is not None:
        return cq.Compound.makeCompound([diag_mod, vertical, clamp])

    # Second attempt: vertical member (fallback)
    vert_mod = try_fillet_on_one_blade_long_edge(vertical, "vertical")
    if vert_mod is not None:
        return cq.Compound.makeCompound([diagonal, vert_mod, clamp])

    print("FAILED: Could not apply the requested fillet R=6.35mm to a long blade edge on diagonal or vertical member")
    return model
