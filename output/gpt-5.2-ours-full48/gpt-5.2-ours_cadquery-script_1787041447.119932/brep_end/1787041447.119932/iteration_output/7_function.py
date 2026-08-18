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
    # Using a tiny epsilon below nominal helps OCCT avoid edge-case failures at exact-limit radii.
    R_nom = 6.35
    R_try_list = [R_nom - 0.01, R_nom - 0.05, R_nom - 0.10]  # keep very close to spec

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
        # diagonal member is long in X and Z, thin in Y
        bb = solid.BoundingBox()
        v = cq.Vector(bb.xlen, 0.0, bb.zlen)
        if abs(v.x) + abs(v.z) < 1e-9:
            v = cq.Vector(1, 0, 0)
        return v_unit(v)

    diag_axis = axis_from_bbox(diagonal)
    print(f"Diagonal axis approx (unit): ({diag_axis.x:.3f},{diag_axis.y:.3f},{diag_axis.z:.3f})")

    def edge_dir(edge):
        vs = list(edge.Vertices())
        if len(vs) < 2:
            return None
        p0 = vs[0].Center()
        p1 = vs[-1].Center()
        return v_unit(cq.Vector(p1.x - p0.x, p1.y - p0.y, p1.z - p0.z))

    # OCCT helpers for face type
    def face_type(face):
        try:
            from OCP.BRepAdaptor import BRepAdaptor_Surface
            ad = BRepAdaptor_Surface(face.wrapped)
            return int(ad.GetType())
        except Exception:
            return None

    def is_plane(face):
        try:
            from OCP.GeomAbs import GeomAbs_Plane
            ft = face_type(face)
            return ft == int(GeomAbs_Plane)
        except Exception:
            # fallback via string
            return "PLANE" in str(face.geomType()).upper()

    def try_fillet_edges(solid, edges, radius):
        try:
            from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
            mk = BRepFilletAPI_MakeFillet(solid.wrapped)
            added = 0
            for e in edges:
                mk.Add(float(radius), e.wrapped)
                added += 1
            mk.Build()
            if not mk.IsDone():
                return (False, None, f"BRepFilletAPI_MakeFillet not done (added={added})")
            res_shape = cq.Shape.cast(mk.Shape())
            res_solids = list(res_shape.Solids())
            if len(res_solids) != 1:
                return (False, None, f"Unexpected solids after fillet: {len(res_solids)}")
            return (True, res_solids[0], "ok")
        except Exception as e:
            return (False, None, str(e))

    # --- Find the missing-radius 'blade' edge ---
    # The previous attempt targeted PLANE-CYLINDER LINE edges; those are typically tangent lines
    # (not sharp), hence "no suitable edges". Here we instead target long, sharp PLANE-PLANE
    # LINE edges aligned with the diagonal axis.

    axis_origin = diagonal.BoundingBox().center

    def perp_dir_to_axis(pnt):
        p = cq.Vector(pnt.x - axis_origin.x, pnt.y - axis_origin.y, pnt.z - axis_origin.z)
        proj = cq.Vector(diag_axis.x, diag_axis.y, diag_axis.z).multiply(dot(p, diag_axis))
        perp = cq.Vector(p.x - proj.x, p.y - proj.y, p.z - proj.z)
        return v_unit(perp)

    def collect_plane_plane_long_edges(solid, axis_u, min_len=80.0, align_cos=0.95):
        cands = []
        for e in solid.Edges():
            try:
                if "LINE" not in str(e.geomType()).upper():
                    continue
                L = float(e.Length())
                if L < min_len:
                    continue
                ed = edge_dir(e)
                if ed is None or abs(dot(ed, axis_u)) < align_cos:
                    continue

                faces = list(e.ancestors(solid, kind="Face"))
                # need at least two adjacent faces; choose plane faces
                plane_faces = [f for f in faces if is_plane(f)]
                if len(plane_faces) < 2:
                    continue

                ec = e.Center()
                pd = perp_dir_to_axis(ec)
                if pd is None:
                    continue

                cands.append({"edge": e, "L": L, "center": ec, "perp": pd, "nPlaneAdj": len(plane_faces)})
            except Exception:
                continue
        return cands

    def cluster_by_perp(candidates, cos_thr=0.98):
        clusters = []
        for d in candidates:
            placed = False
            for cl in clusters:
                if dot(d["perp"], cl["ref"]) > cos_thr:
                    cl["items"].append(d)
                    cl["totalL"] += d["L"]
                    placed = True
                    break
            if not placed:
                clusters.append({"ref": d["perp"], "items": [d], "totalL": d["L"]})
        clusters.sort(key=lambda c: c["totalL"], reverse=True)
        return clusters

    diag_cands = collect_plane_plane_long_edges(diagonal, diag_axis)
    print(f"Diagonal plane-plane LINE edge candidates: {len(diag_cands)}")
    for i, d in enumerate(sorted(diag_cands, key=lambda x: x["L"], reverse=True)[:12]):
        c = d["center"]
        p = d["perp"]
        print(f"  cand[{i}] L={d['L']:.3f} center=({c.x:.3f},{c.y:.3f},{c.z:.3f}) perp=({p.x:.3f},{p.y:.3f},{p.z:.3f}) nPlaneAdj={d['nPlaneAdj']}")

    target_solid_name = "diagonal"
    target_solid = diagonal
    target_axis = diag_axis
    target_other = (vertical, clamp)

    # If no candidates on diagonal, try the vertical member (it also looks like a 'blade' in views)
    if not diag_cands:
        # axis for vertical is Z
        z_axis = cq.Vector(0, 0, 1)
        axis_origin_v = vertical.BoundingBox().center

        def perp_dir_to_axis_v(pnt):
            p = cq.Vector(pnt.x - axis_origin_v.x, pnt.y - axis_origin_v.y, pnt.z - axis_origin_v.z)
            proj = z_axis.multiply(p.z)
            perp = cq.Vector(p.x - proj.x, p.y - proj.y, p.z - proj.z)
            return v_unit(perp)

        def collect_vertical_edges(solid, min_len=150.0, align_cos=0.98):
            cands = []
            for e in solid.Edges():
                try:
                    if "LINE" not in str(e.geomType()).upper():
                        continue
                    L = float(e.Length())
                    if L < min_len:
                        continue
                    ed = edge_dir(e)
                    if ed is None or abs(ed.z) < align_cos:
                        continue
                    faces = list(e.ancestors(solid, kind="Face"))
                    plane_faces = [f for f in faces if is_plane(f)]
                    if len(plane_faces) < 2:
                        continue
                    ec = e.Center()
                    pd = perp_dir_to_axis_v(ec)
                    if pd is None:
                        continue
                    cands.append({"edge": e, "L": L, "center": ec, "perp": pd, "nPlaneAdj": len(plane_faces)})
                except Exception:
                    continue
            return cands

        vert_cands = collect_vertical_edges(vertical)
        print(f"Vertical plane-plane LINE edge candidates: {len(vert_cands)}")
        for i, d in enumerate(sorted(vert_cands, key=lambda x: x["L"], reverse=True)[:12]):
            c = d["center"]
            p = d["perp"]
            print(f"  vcand[{i}] L={d['L']:.3f} center=({c.x:.3f},{c.y:.3f},{c.z:.3f}) perp=({p.x:.3f},{p.y:.3f},{p.z:.3f}) nPlaneAdj={d['nPlaneAdj']}")

        if vert_cands:
            target_solid_name = "vertical"
            target_solid = vertical
            target_axis = z_axis
            target_other = (diagonal, clamp)
            diag_cands = vert_cands  # reuse downstream
        else:
            print("No suitable long sharp plane-plane edge found on diagonal or vertical; returning original model")
            return model

    clusters = cluster_by_perp(diag_cands, cos_thr=0.98)
    print(f"{target_solid_name}: perp-direction clusters: {len(clusters)}")
    for i, cl in enumerate(clusters[:8]):
        r = cl["ref"]
        print(f"  cluster[{i}] totalL={cl['totalL']:.3f} nEdges={len(cl['items'])} ref=({r.x:.3f},{r.y:.3f},{r.z:.3f})")

    # Take the best (longest total length) cluster as "one long edge" (may be split into segments)
    target_cluster = clusters[0]
    target_edges = [d["edge"] for d in target_cluster["items"]]

    print(f"Attempting fillet on {target_solid_name} with {len(target_edges)} segment(s) of one long edge.")

    modified = None
    last_msg = None
    for r in R_try_list:
        print(f"  Fillet attempt radius={r:.3f} mm (nom={R_nom:.3f})")
        ok, mod, msg = try_fillet_edges(target_solid, target_edges, r)
        print(f"    result ok={ok}, msg={msg}")
        last_msg = msg
        if ok:
            modified = mod
            break

    if modified is None:
        # Fallback: try only the single longest segment (sometimes multi-edge fillet fails)
        longest = max(target_cluster["items"], key=lambda x: x["L"])
        print(f"Fallback: attempting fillet only on the longest segment L={longest['L']:.3f}")
        for r in R_try_list:
            print(f"  Fallback fillet attempt radius={r:.3f} mm")
            ok, mod, msg = try_fillet_edges(target_solid, [longest["edge"]], r)
            print(f"    result ok={ok}, msg={msg}")
            last_msg = msg
            if ok:
                modified = mod
                break

    if modified is None:
        print(f"FAILED: could not apply requested fillet. Last message: {last_msg}")
        return model

    # Reassemble compound preserving other solids
    if target_solid_name == "diagonal":
        return cq.Compound.makeCompound([modified, vertical, clamp])
    else:
        return cq.Compound.makeCompound([diagonal, modified, clamp])
