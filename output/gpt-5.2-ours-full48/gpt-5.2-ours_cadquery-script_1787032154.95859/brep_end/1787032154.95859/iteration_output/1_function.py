def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args.get("input_file", ""))
    if not input_file or not os.path.exists(input_file):
        raise ValueError(f"Missing or invalid args['input_file']: {input_file}")

    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    solids = list(shape.Solids())
    print(f"Loaded STEP: {input_file}")
    print(f"Num solids: {len(solids)}")
    for i, s in enumerate(solids):
        bb = s.BoundingBox()
        print(f"  solid[{i}] vol={s.Volume():.3f} bbox=({bb.xlen:.2f},{bb.ylen:.2f},{bb.zlen:.2f})")

    if not solids:
        raise ValueError("No solids found in STEP")

    # Housing = largest solid, insert = second
    solids_sorted = sorted(solids, key=lambda s: s.Volume(), reverse=True)
    housing = solids_sorted[0]
    insert = solids_sorted[1] if len(solids_sorted) > 1 else None

    hb = housing.BoundingBox()
    print(f"Housing bbox: xmin={hb.xmin:.3f} xmax={hb.xmax:.3f} ymin={hb.ymin:.3f} ymax={hb.ymax:.3f} zmin={hb.zmin:.3f} zmax={hb.zmax:.3f}")

    def safe_normal(face):
        # Try normalAt on center; fall back to param-space
        try:
            c = face.Center()
            n = face.normalAt(c)
        except Exception:
            try:
                n = face.normalAt(0.0, 0.0)
            except Exception:
                n = cq.Vector(0, 1, 0)
        L = n.Length if hasattr(n, "Length") else 1.0
        if not L:
            L = 1.0
        return cq.Vector(n.x / L, n.y / L, n.z / L)

    def hcode(obj):
        try:
            return obj.wrapped.HashCode(2147483647)
        except Exception:
            try:
                return obj.HashCode(2147483647)
            except Exception:
                return id(obj)

    # 1) Identify the top deck face: highest face near hb.ymax with outward normal having +Y component.
    faces = list(housing.Faces())
    face_cands = []
    for f in faces:
        bb = f.BoundingBox()
        if bb.ymax < (hb.ymax - 0.05 * hb.ylen):
            continue
        n = safe_normal(f)
        if n.y < 0.15:
            continue
        try:
            area = f.Area()
        except Exception:
            area = bb.xlen * bb.zlen
        # sort by highest y first, then biggest area
        face_cands.append((bb.ymax, area, f))

    if not face_cands:
        raise ValueError("Failed to find a top deck face candidate near the top of the housing")

    face_cands.sort(key=lambda t: (t[0], t[1]), reverse=True)
    top_face = face_cands[0][2]
    top_bb = top_face.BoundingBox()
    print(f"Chosen top face: ymax={top_bb.ymax:.3f} ymin={top_bb.ymin:.3f} xLen={top_bb.xlen:.3f} zLen={top_bb.zlen:.3f}")

    # 2) From that face, find the inner wire (aperture loop). Top face should have outer + inner wire(s).
    wires = list(top_face.Wires())
    print(f"Top face wire count: {len(wires)}")

    if len(wires) < 2:
        # Sometimes STEP may split faces; still try to find a smaller wire if present
        raise ValueError("Top face does not appear to contain an inner wire (aperture loop); cannot reliably select slot-mouth edges")

    outer_metric = hb.xlen * hb.zlen
    wire_cands = []
    for i, w in enumerate(wires):
        wbb = w.BoundingBox()
        metric = wbb.xlen * wbb.zlen
        # Inner loop should be much smaller than the full housing footprint, but not tiny
        print(f"  wire[{i}] bbox xLen={wbb.xlen:.3f} zLen={wbb.zlen:.3f} metric={metric:.3f} center=({wbb.center.x:.3f},{wbb.center.y:.3f},{wbb.center.z:.3f})")
        if metric < 0.60 * outer_metric and metric > 0.0005 * outer_metric:
            # Prefer loops that are closer to the middle of the housing in XZ
            dx = abs(wbb.center.x - hb.center.x) / (hb.xlen + 1e-9)
            dz = abs(wbb.center.z - hb.center.z) / (hb.zlen + 1e-9)
            score = metric - 0.05 * (dx + dz)  # bigger inner loop better; slight preference for centered
            wire_cands.append((score, w))

    if not wire_cands:
        raise ValueError("Could not identify an inner aperture wire on the top face")

    wire_cands.sort(key=lambda t: t[0], reverse=True)
    inner_wire = wire_cands[0][1]
    inner_wbb = inner_wire.BoundingBox()
    print(f"Chosen inner wire: xLen={inner_wbb.xlen:.3f} zLen={inner_wbb.zlen:.3f} center=({inner_wbb.center.x:.3f},{inner_wbb.center.y:.3f},{inner_wbb.center.z:.3f})")

    # 3) Get edges of that wire and fillet them (slot mouth perimeter only).
    inner_edges = list(inner_wire.Edges())
    # Deduplicate by hash
    uniq = []
    seen = set()
    for e in inner_edges:
        eh = hcode(e)
        if eh in seen:
            continue
        seen.add(eh)
        uniq.append(e)

    print(f"Inner wire edges: {len(inner_edges)} (unique={len(uniq)})")
    for k, e in enumerate(uniq[:10]):
        ebb = e.BoundingBox()
        print(f"  edge[{k}] bbox y=({ebb.ymin:.3f},{ebb.ymax:.3f}) xLen={ebb.xlen:.3f} zLen={ebb.zlen:.3f}")

    if len(uniq) < 4:
        print("Warning: fewer than 4 unique edges found on inner wire; proceeding anyway")

    # Apply the requested 2mm fillet to housing only
    housing_wp = cq.Workplane(obj=housing)
    try:
        housing_fillet = housing_wp.newObject(uniq).fillet(2.0).val()
    except Exception as exc:
        raise ValueError(f"Fillet failed on inner wire edges with radius 2.0mm: {exc}")

    if insert is not None:
        assy = cq.Assembly()
        assy.add(housing_fillet, name="housing")
        assy.add(insert, name="insert")
        return assy

    return housing_fillet
