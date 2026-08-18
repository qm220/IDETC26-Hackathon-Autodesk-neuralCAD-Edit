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
    R = R_req - 1e-3  # tiny epsilon for robustness

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

    def face_normal(face):
        try:
            n = face.normalAt(face.Center())
            return v_unit(n)
        except Exception:
            return None

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

    # Approximate diagonal member axis direction from its bounding box (thin in Y, long in XZ)
    bb = diagonal.BoundingBox()
    axis = cq.Vector(bb.xlen, 0.0, bb.zlen)
    axis_u = v_unit(axis) if (abs(axis.x) + abs(axis.z)) > 1e-9 else cq.Vector(1, 0, 0)
    print(f"Diagonal axis approx (unit): ({axis_u.x:.3f},{axis_u.y:.3f},{axis_u.z:.3f})")

    # Find 'blade long edge' candidates on diagonal member:
    # long straight LINE edge between a longitudinal PLANE flat and an OD CYLINDER.
    cand = []
    for e in diagonal.Edges():
        try:
            if "LINE" not in gtype(e):
                continue
            L = float(e.Length())
            if L < 120.0:
                continue

            faces = list(e.ancestors(diagonal, kind="Face"))
            if len(faces) != 2:
                continue
            ftypes = {gtype(f) for f in faces}
            if not ("PLANE" in ftypes and "CYLINDER" in ftypes):
                continue

            pf = next((f for f in faces if gtype(f) == "PLANE"), None)
            pn = face_normal(pf) if pf else None
            if pn is None:
                continue

            # Prefer longitudinal side flats: plane normal mostly in XZ (not Y)
            if abs(pn.y) > 0.35:
                continue

            ed = edge_dir(e)
            if ed is None:
                continue
            if abs(dot(ed, axis_u)) < 0.93:
                continue

            ec = e.Center()
            cand.append((L, ec, pn, e))
        except Exception:
            continue

    cand.sort(key=lambda t: t[0], reverse=True)
    print(f"Diagonal candidate long blade edges found: {len(cand)}")
    for i, (L, ec, pn, _) in enumerate(cand[:10]):
        print(
            f"  cand[{i}] L={L:.3f} center=({ec.x:.3f},{ec.y:.3f},{ec.z:.3f}) "
            f"plane_n=({pn.x:.2f},{pn.y:.2f},{pn.z:.2f})"
        )

    if not cand:
        print("No suitable diagonal blade-edge candidates found; returning original model")
        return model

    # IMPORTANT change vs last iteration:
    # The request is ONE long edge. Last attempt tried filleting multiple long edges at once,
    # which can fail for large R due to fillet interactions.
    # So: try candidates one-by-one until one succeeds.
    diagonal_mod = None
    for idx, (L, ec, pn, e) in enumerate(cand[:6]):
        print(f"Attempting fillet on diagonal cand[{idx}] only: L={L:.3f}, R={R:.3f} mm")
        ok, newSolid, msg = try_fillet_one_edge(diagonal, e)
        print(f"  result: ok={ok}, msg={msg}")
        if ok:
            diagonal_mod = newSolid
            print(f"SUCCESS: fillet applied on ONE diagonal long edge (cand[{idx}])")
            break

    if diagonal_mod is None:
        # Fallback attempt: sometimes 'blade' could refer to the vertical member long sharp edge.
        # Try filleting ONE longest straight edge on vertical member where two planes meet.
        print("Diagonal one-edge fillet did not succeed. Trying fallback on vertical member...")

        # Vertical axis is Z
        z_u = cq.Vector(0, 0, 1)
        vcand = []
        for e in vertical.Edges():
            try:
                if "LINE" not in gtype(e):
                    continue
                L = float(e.Length())
                if L < 200.0:
                    continue
                faces = list(e.ancestors(vertical, kind="Face"))
                if len(faces) != 2:
                    continue
                ftypes = [gtype(f) for f in faces]
                if not (ftypes.count("PLANE") == 2):
                    continue
                ed = edge_dir(e)
                if ed is None or abs(dot(ed, z_u)) < 0.98:
                    continue

                # Exclude edges near clamp (keep those far from origin in Z)
                ec = e.Center()
                if abs(ec.z) < 80:
                    continue

                vcand.append((L, ec, e))
            except Exception:
                continue

        vcand.sort(key=lambda t: t[0], reverse=True)
        print(f"Vertical candidate long sharp edges found: {len(vcand)}")
        for i, (L, ec, _) in enumerate(vcand[:10]):
            print(f"  v_cand[{i}] L={L:.3f} center=({ec.x:.3f},{ec.y:.3f},{ec.z:.3f})")

        vertical_mod = None
        for idx, (L, ec, e) in enumerate(vcand[:4]):
            print(f"Attempting fillet on vertical v_cand[{idx}] only: L={L:.3f}, R={R:.3f} mm")
            ok, newSolid, msg = try_fillet_one_edge(vertical, e)
            print(f"  result: ok={ok}, msg={msg}")
            if ok:
                vertical_mod = newSolid
                print(f"SUCCESS: fillet applied on ONE vertical long edge (v_cand[{idx}])")
                break

        if vertical_mod is not None:
            return cq.Compound.makeCompound([diagonal, vertical_mod, clamp])

        print("FAILED: could not apply requested fillet on diagonal or vertical member")
        return model

    return cq.Compound.makeCompound([diagonal_mod, vertical, clamp])
