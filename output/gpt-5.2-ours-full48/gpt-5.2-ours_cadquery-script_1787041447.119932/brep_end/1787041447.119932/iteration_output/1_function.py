def my_cad_function(args):
    import cadquery as cq
    import os

    in_path = os.path.expanduser(args.get("input_file", ""))
    if not in_path or not os.path.exists(in_path):
        raise ValueError(f"Input STEP file not found: {in_path}")

    model = cq.importers.importStep(in_path)
    root = model.val() if hasattr(model, "val") else model
    solids = list(root.Solids())

    print(f"Loaded STEP: {in_path}")
    print(f"Num solids: {len(solids)}")

    def bb_info(s):
        bb = s.BoundingBox()
        return bb.xlen, bb.ylen, bb.zlen, bb.center

    for i, s in enumerate(solids):
        xlen, ylen, zlen, c = bb_info(s)
        print(f"Solid[{i}] bbox: x={xlen:.3f} y={ylen:.3f} z={zlen:.3f} center=({c.x:.3f},{c.y:.3f},{c.z:.3f})")

    # Identify clamp (largest Y extent), the two long members are the other solids
    clamp_i = None
    diag_i = None
    vert_i = None
    if len(solids) >= 3:
        y_extents = [(i, s.BoundingBox().ylen) for i, s in enumerate(solids)]
        clamp_i = max(y_extents, key=lambda t: t[1])[0]
        rem = [i for i in range(len(solids)) if i != clamp_i]
        # vertical: largest Z
        vert_i = max(rem, key=lambda i: solids[i].BoundingBox().zlen)
        diag_i = [i for i in rem if i != vert_i][0]
        print(f"Identified clamp_i={clamp_i}, vertical_i={vert_i}, diagonal_i={diag_i}")
    else:
        print("WARNING: Expected 3 solids; proceeding with first solid only.")

    # Requested fillet radius: 0.635 cm = 6.35 mm
    r = 6.35

    def gtype(obj):
        try:
            return str(obj.geomType()).upper()
        except Exception:
            return "UNKNOWN"

    def attempt_fillet_one_long_edge(shape, shape_name="shape"):
        """Try to fillet exactly one long edge on the given shape.
        Returns (new_shape, debug_dict) or (None, debug_dict)"""
        # Collect linear edges
        line_edges = []
        for e in shape.Edges():
            try:
                if "LINE" not in gtype(e):
                    continue
                L = float(e.Length())
                if L <= 1e-6:
                    continue
                mp = e.Center()
                # Prefer manifold edges with 2 adjacent faces
                faces = list(e.ancestors(shape, kind="Face"))
                fts = [gtype(f) for f in faces]
                line_edges.append((e, L, (mp.x, mp.y, mp.z), fts, len(faces)))
            except Exception:
                continue

        line_edges.sort(key=lambda t: t[1], reverse=True)
        dbg = {
            "shape_name": shape_name,
            "num_line_edges": len(line_edges),
        }

        if not line_edges:
            print(f"{shape_name}: no LINE edges found")
            return None, dbg

        maxL = line_edges[0][1]
        print(f"{shape_name}: max LINE edge length = {maxL:.3f}")
        print(f"{shape_name}: top 15 LINE edge candidates:")
        for k, (_, L, c, fts, nf) in enumerate(line_edges[:15]):
            print(f"  cand[{k}] L={L:.3f} center=({c[0]:.3f},{c[1]:.3f},{c[2]:.3f}) nFaces={nf} faces={fts}")

        # Try progressively broader candidate sets; stop at first success (exactly one edge filleted)
        thresholds = [0.98, 0.90, 0.80, 0.70, 0.60, 0.50]
        for thr in thresholds:
            subset = [t for t in line_edges if t[1] >= thr * maxL]
            # prioritize edges that look like a sharp boundary (2 faces) rather than seams
            subset.sort(key=lambda t: (-(t[4] == 2), -t[1]))
            print(f"{shape_name}: trying threshold {thr:.2f} -> {len(subset)} candidate edge(s)")

            for idx, (edge, L, c, fts, nf) in enumerate(subset[:30]):
                # Skip edges that are likely seam edges (often have 1 face) but still allow if needed
                try:
                    wp = cq.Workplane(obj=shape).newObject([edge])
                    new_shape = wp.fillet(r).val()
                    print(f"{shape_name}: SUCCESS fillet on candidate idx={idx} L={L:.3f} center=({c[0]:.3f},{c[1]:.3f},{c[2]:.3f}) faces={fts}")
                    dbg.update({
                        "success": True,
                        "edge_length": L,
                        "edge_center": c,
                        "edge_adj_faces": fts,
                        "edge_adj_face_count": nf,
                        "threshold_used": thr,
                    })
                    return new_shape, dbg
                except Exception as e:
                    # Common if the edge is tangent (no sharp corner) or radius too large locally
                    print(f"{shape_name}: fillet failed on cand idx={idx} L={L:.3f} center=({c[0]:.3f},{c[1]:.3f},{c[2]:.3f}) nFaces={nf} err={e}")
                    continue

        dbg.update({"success": False})
        print(f"{shape_name}: FAILED to apply fillet r={r}mm to any long linear edge")
        return None, dbg

    # Apply to the intended long member first (diagonal), then fall back to vertical if needed
    if len(solids) >= 3:
        clamp = solids[clamp_i]
        diagonal = solids[diag_i]
        vertical = solids[vert_i]

        diag_mod, diag_dbg = attempt_fillet_one_long_edge(diagonal, "diagonal")
        if diag_mod is not None:
            out = cq.Compound.makeCompound([diag_mod, vertical, clamp])
            return out

        vert_mod, vert_dbg = attempt_fillet_one_long_edge(vertical, "vertical")
        if vert_mod is not None:
            out = cq.Compound.makeCompound([diagonal, vert_mod, clamp])
            return out

        print("No fillet could be applied on diagonal or vertical member; returning original model")
        return model

    # Fallback: single-solid file
    base = solids[0]
    mod, dbg = attempt_fillet_one_long_edge(base, "single_solid")
    return mod if mod is not None else model
