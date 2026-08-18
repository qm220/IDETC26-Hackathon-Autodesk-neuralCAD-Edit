def my_cad_function(args):
    import cadquery as cq
    import os

    in_path = os.path.expanduser(args.get('input_file', ''))
    if not in_path or not os.path.exists(in_path):
        raise ValueError(f"Input STEP file not found: {in_path}")

    model = cq.importers.importStep(in_path)
    root = model.val() if hasattr(model, 'val') else model

    solids = list(root.Solids())
    print(f"Loaded STEP: {in_path}")
    print(f"Num solids: {len(solids)}")

    if len(solids) < 3:
        # Still try to proceed on single solid, but print info.
        print("WARNING: Expected 3 solids; proceeding with whatever is present.")

    def bbox_dims(s):
        bb = s.BoundingBox()
        return bb.xlen, bb.ylen, bb.zlen, bb

    # Identify clamp (largest Y extent), vertical (largest Z extent of remaining), diagonal (the other)
    binfo = []
    for i, s in enumerate(solids):
        xlen, ylen, zlen, bb = bbox_dims(s)
        binfo.append((i, xlen, ylen, zlen, bb))
        c = bb.center
        print(f"Solid[{i}] bbox: x={xlen:.3f} y={ylen:.3f} z={zlen:.3f} center=({c.x:.3f},{c.y:.3f},{c.z:.3f})")

    if len(solids) >= 3:
        clamp_i = max(binfo, key=lambda t: t[2])[0]
        rem = [t for t in binfo if t[0] != clamp_i]
        vertical_i = max(rem, key=lambda t: t[3])[0]
        diagonal_i = [t[0] for t in rem if t[0] != vertical_i][0]

        print(f"Identified clamp_i={clamp_i}, vertical_i={vertical_i}, diagonal_i={diagonal_i}")

        clamp = solids[clamp_i]
        vertical = solids[vertical_i]
        diagonal = solids[diagonal_i]
    else:
        # Fallback: treat whole thing as the target.
        clamp = None
        vertical = None
        diagonal = solids[0]

    # Target fillet radius: 0.635 cm = 6.35 mm
    r = 6.35

    def gtype(obj):
        try:
            return str(obj.geomType()).upper()
        except Exception:
            return "UNKNOWN"

    # Find candidate long linear sharp edges on diagonal member: LINE edges with (PLANE, CYLINDER) adjacent faces
    cand = []
    for e in diagonal.Edges():
        try:
            et = gtype(e)
            if 'LINE' not in et:
                continue
            L = float(e.Length())
            if L < 10.0:
                continue
            faces = list(e.ancestors(diagonal, kind='Face'))
            fts = [gtype(f) for f in faces]
            has_plane = any(('PLANE' in t) or ('PLANAR' in t) for t in fts)
            has_cyl = any('CYL' in t for t in fts)
            if not (has_plane and has_cyl):
                continue
            mp = e.Center()
            cand.append((e, L, (mp.x, mp.y, mp.z), fts))
        except Exception:
            continue

    cand.sort(key=lambda t: t[1], reverse=True)
    print(f"Diagonal candidate edges (LINE + PLANE/CYL): {len(cand)}")
    for k, (_, L, c, fts) in enumerate(cand[:20]):
        print(f"  cand[{k}] L={L:.3f} center=({c[0]:.3f},{c[1]:.3f},{c[2]:.3f}) faces={fts}")

    if not cand:
        print("WARNING: No candidate edges found on diagonal member. Returning original model.")
        return model

    # Select edges: take those close to the maximum length to approximate the 'long blade edge' chain(s)
    maxL = cand[0][1]
    sel_edges = [t[0] for t in cand if t[1] >= 0.80 * maxL]
    print(f"Selected {len(sel_edges)} edge(s) for fillet with r={r} mm (maxL={maxL:.3f})")

    # Apply fillet to the diagonal solid only
    diag_wp = cq.Workplane(obj=diagonal).newObject(sel_edges)
    try:
        diag_mod = diag_wp.fillet(r).val()
        print("Fillet applied successfully on diagonal member.")
    except Exception as e:
        print(f"ERROR: Fillet failed with r={r} mm: {e}")
        # Return original model for inspection; next iteration can refine selection or approach.
        return model

    # Rebuild compound with other solids unchanged (keep as multi-solid)
    if clamp is not None and vertical is not None:
        out = cq.Compound.makeCompound([diag_mod, vertical, clamp])
        return out
    else:
        return diag_mod
