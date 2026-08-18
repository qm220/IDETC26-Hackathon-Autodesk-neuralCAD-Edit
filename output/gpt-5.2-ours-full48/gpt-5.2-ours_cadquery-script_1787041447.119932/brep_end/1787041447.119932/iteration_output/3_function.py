def my_cad_function(args):
    import cadquery as cq
    import os, math

    # --- Load STEP ---
    in_path = os.path.expanduser(args.get("input_file", ""))
    if not in_path or not os.path.exists(in_path):
        raise ValueError(f"Input STEP file not found: {in_path}")

    model = cq.importers.importStep(in_path)
    root = model.val() if hasattr(model, "val") else model
    solids = list(root.Solids())

    print(f"Loaded STEP: {in_path}")
    print(f"Num solids: {len(solids)}")

    # Requested: R=0.635 cm = 6.35 mm
    # Use a tiny epsilon under to avoid exact-limit robustness issues
    R = 6.35 - 1e-3

    for i, s in enumerate(solids):
        bb = s.BoundingBox()
        c = bb.center
        print(f"Solid[{i}] bbox: x={bb.xlen:.3f} y={bb.ylen:.3f} z={bb.zlen:.3f} center=({c.x:.3f},{c.y:.3f},{c.z:.3f})")

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
        L = math.sqrt(v.x*v.x + v.y*v.y + v.z*v.z)
        if L < 1e-12:
            return None
        return cq.Vector(v.x/L, v.y/L, v.z/L)

    def dot(a, b):
        return a.x*b.x + a.y*b.y + a.z*b.z

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

    # Approximate diagonal member axis direction from its bounding box (thin in Y, long in XZ)
    bb = diagonal.BoundingBox()
    axis = cq.Vector(bb.xlen, 0.0, bb.zlen)
    axis_u = v_unit(axis) if (abs(axis.x) + abs(axis.z)) > 1e-9 else cq.Vector(1, 0, 0)

    print(f"Diagonal axis approx (unit): ({axis_u.x:.3f},{axis_u.y:.3f},{axis_u.z:.3f})")

    # --- Find the 'blade long edge' candidates on the diagonal member ---
    # Interpret as: long straight edge where a longitudinal planar flat meets the OD cylinder.
    # Heuristics:
    #  - Edge is LINE and long
    #  - Adjacent faces include (PLANE, CYLINDER)
    #  - Plane normal not ~Y (exclude top/bottom flats); i.e. |ny| small
    #  - Edge direction aligned with member axis
    cand_edges = []
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

            # Get plane face and its normal
            pf = next((f for f in faces if gtype(f) == "PLANE"), None)
            if pf is None:
                continue
            pn = face_normal(pf)
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
            cand_edges.append((L, ec, pn, e))
        except Exception:
            continue

    cand_edges.sort(key=lambda t: t[0], reverse=True)
    print(f"Diagonal candidate long blade edges found: {len(cand_edges)}")
    for i, (L, ec, pn, _) in enumerate(cand_edges[:10]):
        print(f"  cand[{i}] L={L:.3f} center=({ec.x:.3f},{ec.y:.3f},{ec.z:.3f}) plane_n=({pn.x:.2f},{pn.y:.2f},{pn.z:.2f})")

    if not cand_edges:
        print("No suitable diagonal blade-edge candidates found with heuristics; returning original model")
        return model

    # Keep only the longest group (in case STEP splits it into 2-3 segments)
    maxL = cand_edges[0][0]
    use_edges = [t[3] for t in cand_edges if t[0] >= 0.85 * maxL]
    print(f"Attempting fillet on {len(use_edges)} edge segment(s) (R={R:.3f} mm)")

    # --- Apply fillet using OCP directly (more reliable than Workplane edge selection) ---
    try:
        from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet

        mk = BRepFilletAPI_MakeFillet(diagonal.wrapped)
        for ed in use_edges:
            mk.Add(R, ed.wrapped)

        mk.Build()
        if not mk.IsDone():
            raise RuntimeError("BRepFilletAPI_MakeFillet not done")

        res_shape = cq.Shape.cast(mk.Shape())
        res_solids = list(res_shape.Solids())
        if len(res_solids) == 1:
            diagonal_mod = res_solids[0]
        else:
            # fallback (shouldn't happen)
            diagonal_mod = res_shape

        print("SUCCESS: fillet applied on diagonal member")
        return cq.Compound.makeCompound([diagonal_mod, vertical, clamp])

    except Exception as e:
        print(f"FAILED: fillet attempt on diagonal member: {e}")
        return model
