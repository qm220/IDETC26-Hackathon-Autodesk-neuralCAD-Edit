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

    # Requested: R=0.635 cm = 6.35 mm
    R_req = 6.35
    R = R_req - 1e-3  # small epsilon for robustness

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

    def gtype(obj):
        try:
            return str(obj.geomType()).upper()
        except Exception:
            return "UNKNOWN"

    def v_unit(v):
        L = math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z)
        if L < 1e-12:
            return None
        return cq.Vector(v.x / L, v.y / L, v.z / L)

    def dot(a, b):
        return a.x * b.x + a.y * b.y + a.z * b.z

    def edge_dir(edge):
        try:
            vs = list(edge.Vertices())
            if len(vs) < 2:
                return None
            p0 = vs[0].Center()
            p1 = vs[-1].Center()
            d = cq.Vector(p1.x - p0.x, p1.y - p0.y, p1.z - p0.z)
            return v_unit(d)
        except Exception:
            return None

    def try_fillet_one_edge(solid, edge):
        """Attempt fillet on a single edge (constant radius). Return (ok, newSolidOrNone, msg)."""
        try:
            from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet

            mk = BRepFilletAPI_MakeFillet(solid.wrapped)
            mk.Add(R, edge.wrapped)
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

    def axis_from_bbox(solid, prefer="XZ"):
        bb = solid.BoundingBox()
        # For diagonal, long in X and Z but thin in Y
        if prefer == "XZ":
            v = cq.Vector(bb.xlen, 0.0, bb.zlen)
            if abs(v.x) + abs(v.z) < 1e-9:
                v = cq.Vector(1, 0, 0)
            return v_unit(v)
        # For vertical, assume Z
        if prefer == "Z":
            return cq.Vector(0, 0, 1)
        # Fallback: choose longest bbox dimension axis
        if bb.xlen >= bb.ylen and bb.xlen >= bb.zlen:
            return cq.Vector(1, 0, 0)
        if bb.ylen >= bb.xlen and bb.ylen >= bb.zlen:
            return cq.Vector(0, 1, 0)
        return cq.Vector(0, 0, 1)

    diag_axis = axis_from_bbox(diagonal, prefer="XZ")
    vert_axis = axis_from_bbox(vertical, prefer="Z")
    print(f"Diagonal axis approx (unit): ({diag_axis.x:.3f},{diag_axis.y:.3f},{diag_axis.z:.3f})")

    def collect_candidates(solid, axis_u, min_len):
        cands = []
        for e in solid.Edges():
            try:
                L = float(e.Length())
                if L < min_len:
                    continue

                ed = edge_dir(e)
                if ed is None:
                    continue

                # Prefer edges running along the member axis
                if abs(dot(ed, axis_u)) < 0.95:
                    continue

                faces = list(e.ancestors(solid, kind="Face"))
                if len(faces) != 2:
                    continue
                ftypes = [gtype(f) for f in faces]
                n_plane = sum(1 for t in ftypes if t == "PLANE")

                # Only consider edges that touch at least one plane (likely a sharp break)
                if n_plane < 1:
                    continue

                et = gtype(e)
                # Score: prioritize plane-plane sharp edges over plane-cylinder.
                score = 0
                score += 2000 if n_plane == 2 else 1000
                score += 100 if "LINE" in et else 0
                score += L

                ec = e.Center()
                cands.append({
                    "score": score,
                    "L": L,
                    "center": ec,
                    "etype": et,
                    "ftypes": ftypes,
                    "edge": e,
                })
            except Exception:
                continue
        cands.sort(key=lambda d: d["score"], reverse=True)
        return cands

    # Main attempt: diagonal member ("blade")
    diag_cands = collect_candidates(diagonal, diag_axis, min_len=100.0)
    print(f"Diagonal long-edge candidates (plane-touching) found: {len(diag_cands)}")
    for i, d in enumerate(diag_cands[:12]):
        c = d["center"]
        print(f"  diag[{i}] score={d['score']:.1f} L={d['L']:.3f} etype={d['etype']} ftypes={d['ftypes']} center=({c.x:.3f},{c.y:.3f},{c.z:.3f})")

    diagonal_mod = None
    for i, d in enumerate(diag_cands[:10]):
        print(f"Attempting fillet on diagonal candidate {i}: L={d['L']:.3f}, R={R:.3f} mm")
        ok, newSolid, msg = try_fillet_one_edge(diagonal, d["edge"])
        print(f"  result: ok={ok}, msg={msg}")
        if ok:
            diagonal_mod = newSolid
            print(f"SUCCESS: fillet applied on ONE diagonal long edge (candidate {i})")
            break

    if diagonal_mod is not None:
        return cq.Compound.makeCompound([diagonal_mod, vertical, clamp])

    # Fallback: vertical member long edge
    vert_cands = collect_candidates(vertical, vert_axis, min_len=150.0)
    print(f"Vertical long-edge candidates (plane-touching) found: {len(vert_cands)}")
    for i, d in enumerate(vert_cands[:12]):
        c = d["center"]
        print(f"  vert[{i}] score={d['score']:.1f} L={d['L']:.3f} etype={d['etype']} ftypes={d['ftypes']} center=({c.x:.3f},{c.y:.3f},{c.z:.3f})")

    vertical_mod = None
    for i, d in enumerate(vert_cands[:10]):
        print(f"Attempting fillet on vertical candidate {i}: L={d['L']:.3f}, R={R:.3f} mm")
        ok, newSolid, msg = try_fillet_one_edge(vertical, d["edge"])
        print(f"  result: ok={ok}, msg={msg}")
        if ok:
            vertical_mod = newSolid
            print(f"SUCCESS: fillet applied on ONE vertical long edge (candidate {i})")
            break

    if vertical_mod is not None:
        return cq.Compound.makeCompound([diagonal, vertical_mod, clamp])

    # Final fallback: clamp (in case "blade" was interpreted differently)
    clamp_axis = axis_from_bbox(clamp, prefer="AUTO")
    clamp_cands = collect_candidates(clamp, clamp_axis, min_len=30.0)
    print(f"Clamp edge candidates (plane-touching) found: {len(clamp_cands)}")
    for i, d in enumerate(clamp_cands[:12]):
        c = d["center"]
        print(f"  clamp[{i}] score={d['score']:.1f} L={d['L']:.3f} etype={d['etype']} ftypes={d['ftypes']} center=({c.x:.3f},{c.y:.3f},{c.z:.3f})")

    clamp_mod = None
    for i, d in enumerate(clamp_cands[:10]):
        print(f"Attempting fillet on clamp candidate {i}: L={d['L']:.3f}, R={R:.3f} mm")
        ok, newSolid, msg = try_fillet_one_edge(clamp, d["edge"])
        print(f"  result: ok={ok}, msg={msg}")
        if ok:
            clamp_mod = newSolid
            print(f"SUCCESS: fillet applied on ONE clamp edge (candidate {i})")
            break

    if clamp_mod is not None:
        return cq.Compound.makeCompound([diagonal, vertical, clamp_mod])

    print("FAILED: could not apply requested fillet on any likely long edge")
    return model
