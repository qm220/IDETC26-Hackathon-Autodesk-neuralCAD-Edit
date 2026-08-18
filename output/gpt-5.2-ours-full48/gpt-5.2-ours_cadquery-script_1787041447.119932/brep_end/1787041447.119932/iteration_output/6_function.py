def my_cad_function(args):
    import cadquery as cq
    import os, math

    # --- load ---
    in_path = os.path.expanduser(args.get("input_file", ""))
    if not in_path or not os.path.exists(in_path):
        raise ValueError(f"Input STEP file not found: {in_path}")

    model = cq.importers.importStep(in_path)
    root = model.val() if hasattr(model, "val") else model
    solids = list(root.Solids())

    print(f"Loaded STEP: {in_path}")
    print(f"Num solids: {len(solids)}")

    # Requested: R=0.635 cm = 6.35 mm
    R_req = 6.35
    R = R_req - 1e-3  # epsilon for robustness

    for i, s in enumerate(solids):
        bb = s.BoundingBox()
        c = bb.center
        print(
            f"Solid[{i}] bbox: x={bb.xlen:.3f} y={bb.ylen:.3f} z={bb.zlen:.3f} "
            f"center=({c.x:.3f},{c.y:.3f},{c.z:.3f})"
        )

    if len(solids) != 3:
        print("WARNING: Expected 3 solids; returning original model")
        return model

    # Identify solids: clamp has largest Y extent; vertical has largest Z of remaining
    clamp_i = max(range(3), key=lambda i: solids[i].BoundingBox().ylen)
    rem = [i for i in range(3) if i != clamp_i]
    vert_i = max(rem, key=lambda i: solids[i].BoundingBox().zlen)
    diag_i = [i for i in rem if i != vert_i][0]

    diagonal = solids[diag_i]
    vertical = solids[vert_i]
    clamp = solids[clamp_i]

    print(f"Identified clamp_i={clamp_i}, vertical_i={vert_i}, diagonal_i={diag_i}")

    def v_unit(v):
        L = math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z)
        if L < 1e-12:
            return None
        return cq.Vector(v.x / L, v.y / L, v.z / L)

    def dot(a, b):
        return a.x * b.x + a.y * b.y + a.z * b.z

    def axis_from_bbox(solid):
        # For diagonal: long in X and Z, thin in Y
        bb = solid.BoundingBox()
        v = cq.Vector(bb.xlen, 0.0, bb.zlen)
        if abs(v.x) + abs(v.z) < 1e-9:
            v = cq.Vector(1, 0, 0)
        return v_unit(v)

    diag_axis = axis_from_bbox(diagonal)
    print(f"Diagonal axis approx (unit): ({diag_axis.x:.3f},{diag_axis.y:.3f},{diag_axis.z:.3f})")

    def edge_dir(edge):
        try:
            vs = list(edge.Vertices())
            if len(vs) < 2:
                return None
            p0 = vs[0].Center()
            p1 = vs[-1].Center()
            return v_unit(cq.Vector(p1.x - p0.x, p1.y - p0.y, p1.z - p0.z))
        except Exception:
            return None

    # OCCT helpers to detect cylinder radius + axis
    def cyl_info(face):
        try:
            from OCP.BRepAdaptor import BRepAdaptor_Surface
            from OCP.GeomAbs import GeomAbs_Cylinder

            ad = BRepAdaptor_Surface(face.wrapped)
            if ad.GetType() != GeomAbs_Cylinder:
                return None
            cyl = ad.Cylinder()
            r = float(cyl.Radius())
            ax = cyl.Axis().Direction()
            axis_u = v_unit(cq.Vector(ax.X(), ax.Y(), ax.Z()))
            return (r, axis_u)
        except Exception:
            return None

    def try_fillet_edges(solid, edges):
        try:
            from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet

            mk = BRepFilletAPI_MakeFillet(solid.wrapped)
            for e in edges:
                mk.Add(R, e.wrapped)
            mk.Build()
            if not mk.IsDone():
                return (False, None, "BRepFilletAPI_MakeFillet not done")

            res_shape = cq.Shape.cast(mk.Shape())
            res_solids = list(res_shape.Solids())
            if len(res_solids) != 1:
                return (False, None, f"Unexpected solids after fillet: {len(res_solids)}")
            return (True, res_solids[0], "ok")
        except Exception as e:
            return (False, None, str(e))

    # --- find the 'blade' long sharp edge: plane<->OD-cylinder boundary ---
    # We target long LINE edges aligned with diagonal axis, with adjacent faces (PLANE, CYLINDER)
    # where CYLINDER radius ~ 6.35 mm (tube OD) and its axis ~ diagonal axis.
    tube_r_nom = 6.35
    r_min, r_max = 5.5, 7.5

    axis_origin = diagonal.BoundingBox().center

    def perp_dir_to_axis(pnt):
        # radial/perpendicular direction from axis line to point
        p = cq.Vector(pnt.x - axis_origin.x, pnt.y - axis_origin.y, pnt.z - axis_origin.z)
        proj = cq.Vector(diag_axis.x, diag_axis.y, diag_axis.z).multiply(dot(p, diag_axis))
        perp = cq.Vector(p.x - proj.x, p.y - proj.y, p.z - proj.z)
        return v_unit(perp)

    candidates = []
    for e in diagonal.Edges():
        try:
            L = float(e.Length())
            if L < 30.0:
                continue
            et = str(e.geomType()).upper()
            if "LINE" not in et:
                continue
            ed = edge_dir(e)
            if ed is None or abs(dot(ed, diag_axis)) < 0.95:
                continue

            faces = list(e.ancestors(diagonal, kind="Face"))
            if len(faces) != 2:
                continue

            # classify adjacent faces
            f0t = str(faces[0].geomType()).upper()
            f1t = str(faces[1].geomType()).upper()
            types = {f0t, f1t}
            if not ("PLANE" in types and "CYLINDER" in types):
                continue

            # pick the cylinder face and validate it looks like the OD tube
            cyl_face = faces[0] if "CYLINDER" in f0t else faces[1]
            info = cyl_info(cyl_face)
            if info is None:
                continue
            r_cyl, cyl_axis_u = info
            if not (r_min <= r_cyl <= r_max):
                continue
            if cyl_axis_u is None or abs(dot(cyl_axis_u, diag_axis)) < 0.90:
                continue

            ec = e.Center()
            pd = perp_dir_to_axis(ec)
            if pd is None:
                continue

            candidates.append({
                "edge": e,
                "L": L,
                "center": ec,
                "perp": pd,
                "r_cyl": r_cyl,
            })
        except Exception:
            continue

    print(f"Diagonal plane-cylinder LINE edge candidates: {len(candidates)}")
    for i, d in enumerate(sorted(candidates, key=lambda x: x["L"], reverse=True)[:12]):
        c = d["center"]
        p = d["perp"]
        print(f"  cand[{i}] L={d['L']:.3f} r_cyl={d['r_cyl']:.3f} center=({c.x:.3f},{c.y:.3f},{c.z:.3f}) perp=({p.x:.3f},{p.y:.3f},{p.z:.3f})")

    if not candidates:
        print("No suitable plane-cylinder long edge found on diagonal member. Returning original model.")
        return model

    # Cluster candidates by perpendicular direction to separate the two long edges of the flat
    clusters = []  # list of {ref_perp, edges, totalL}
    ang_cos = 0.98

    for d in candidates:
        placed = False
        for cl in clusters:
            if dot(d["perp"], cl["ref"]) > ang_cos:
                cl["edges"].append(d)
                cl["totalL"] += d["L"]
                placed = True
                break
        if not placed:
            clusters.append({"ref": d["perp"], "edges": [d], "totalL": d["L"]})

    clusters.sort(key=lambda c: c["totalL"], reverse=True)
    print(f"Perp-direction clusters: {len(clusters)}")
    for i, cl in enumerate(clusters[:6]):
        r = cl["ref"]
        print(f"  cluster[{i}] totalL={cl['totalL']:.3f} nEdges={len(cl['edges'])} ref=({r.x:.3f},{r.y:.3f},{r.z:.3f})")

    # Choose the largest-length cluster as the best representation of a single 'long edge'
    target_cluster = clusters[0]
    target_edges = [d["edge"] for d in target_cluster["edges"]]

    print(f"Attempting fillet on {len(target_edges)} edge segment(s) of one long blade edge. R={R:.3f} mm")
    ok, diagonal_mod, msg = try_fillet_edges(diagonal, target_edges)
    print(f"Fillet result: ok={ok}, msg={msg}")

    if not ok:
        # fallback: try only the single longest edge (sometimes multi-edge fillet fails)
        longest = max(target_cluster["edges"], key=lambda x: x["L"])
        print(f"Fallback: attempting fillet only on the longest segment L={longest['L']:.3f}")
        ok2, diagonal_mod2, msg2 = try_fillet_edges(diagonal, [longest["edge"]])
        print(f"Fallback fillet result: ok={ok2}, msg={msg2}")
        if ok2:
            return cq.Compound.makeCompound([diagonal_mod2, vertical, clamp])
        print("FAILED: could not apply requested fillet to the intended blade long edge")
        return model

    return cq.Compound.makeCompound([diagonal_mod, vertical, clamp])
