def my_cad_function(args):
    import cadquery as cq
    import os, math

    input_file = args.get("input_file", None)
    if not input_file:
        raise ValueError("args['input_file'] not provided")
    input_file = os.path.expanduser(input_file)
    if not os.path.exists(input_file):
        raise ValueError(f"STEP file not found: {input_file}")

    imp = cq.importers.importStep(input_file)
    base = imp.val() if hasattr(imp, "val") else imp

    try:
        solids = list(base.Solids())
    except Exception:
        solids = list(imp.val().Solids())

    print(f"Loaded STEP: {input_file}")
    print(f"Total solids found: {len(solids)}")

    def _bb(s):
        bb = s.BoundingBox()
        return bb, bb.xlen, bb.ylen, bb.zlen

    def _classify(s):
        bb, dx, dy, dz = _bb(s)
        a = sorted([dx, dy, dz])
        if a[0] < 3.5 and a[2] > 20:
            return "plate"
        if max(dx, dy) < 9 and dz > 25:
            return "pin_long"
        if max(dx, dy) < 9 and dz <= 10:
            return "pin_short"
        return "block"

    def _largest_face(wp, selector: str):
        fs = wp.faces(selector).vals()
        if not fs:
            return None
        return max(fs, key=lambda f: f.Area())

    def _inner_wires_from_face(face):
        outer = face.outerWire()
        inners = []
        for w in face.Wires():
            try:
                if not w.isSame(outer):
                    inners.append(w)
            except Exception:
                if w.hashCode() != outer.hashCode():
                    inners.append(w)
        return inners

    def _edge_points(edge, n=25):
        try:
            pts = edge.discretize(n)
            out = []
            for p in pts:
                if isinstance(p, cq.Vector):
                    out.append(p)
                else:
                    out.append(cq.Vector(p.X(), p.Y(), p.Z()))
            return out
        except Exception:
            try:
                return [edge.startPoint(), edge.midPoint(), edge.endPoint()]
            except Exception:
                return []

    def _max_halfwidth_about_centerline(outer_wire, p1, p2):
        v = cq.Vector(p2.x - p1.x, p2.y - p1.y, 0)
        L = math.hypot(v.x, v.y)
        if L < 1e-9:
            return None
        xdir = cq.Vector(v.x / L, v.y / L, 0)
        ydir = cq.Vector(-xdir.y, xdir.x, 0)
        origin = cq.Vector((p1.x + p2.x) * 0.5, (p1.y + p2.y) * 0.5, 0)

        max_abs_y = 0.0
        for e in outer_wire.Edges():
            for pt in _edge_points(e, n=30):
                vv = cq.Vector(pt.x - origin.x, pt.y - origin.y, 0)
                y = vv.dot(ydir)
                max_abs_y = max(max_abs_y, abs(y))
        return max_abs_y

    def _rebuild_plate_from_old(old_plate):
        bb, dx, dy, dz = _bb(old_plate)
        zmid = (bb.zmin + bb.zmax) * 0.5
        thickness = dz

        wp_old = cq.Workplane(obj=old_plate)
        top_face = _largest_face(wp_old, ">Z")
        if top_face is None:
            print("  Plate: could not find >Z face; leaving unchanged")
            return old_plate

        outer_wire = top_face.outerWire()
        inner_wires = _inner_wires_from_face(top_face)

        holes = []  # (centerVector, radius)
        for w in inner_wires:
            edges = list(w.Edges())
            if len(edges) != 1:
                continue
            e = edges[0]
            try:
                if e.geomType() == "CIRCLE":
                    c = e.Center()  # Vector
                    r = float(e.radius())
                    holes.append((cq.Vector(c.x, c.y, c.z), r))
            except Exception:
                continue

        print(f"Plate: dims=({dx:.2f},{dy:.2f},{dz:.2f}) zmid={zmid:.3f} holes_found={len(holes)}")
        if len(holes) < 3:
            print("  WARNING: expected 3 circular holes on plate face; leaving plate unchanged")
            return old_plate

        # Identify end holes as farthest pair among extracted circles
        centers = [h[0] for h in holes]
        radii = [h[1] for h in holes]
        max_d = -1.0
        end_i, end_j = 0, 1
        for i in range(len(centers)):
            for j in range(i + 1, len(centers)):
                d = centers[i].sub(centers[j]).Length
                if d > max_d:
                    max_d = d
                    end_i, end_j = i, j
        p1 = centers[end_i]
        p2 = centers[end_j]

        # Action 2: hole diameter +1mm => radius +0.5mm (apply to all 3 holes)
        new_holes = [(c, r + 0.5) for (c, r) in holes]

        # Actions 1 & 3: change outer profile to a capsule/slot and keep ligament about constant.
        end_r_old = radii[end_i]
        half_w_old = _max_halfwidth_about_centerline(outer_wire, p1, p2)
        if half_w_old is None:
            half_w_old = end_r_old + 3.0
        ligament = max(1.0, half_w_old - end_r_old)  # infer existing half width margin

        end_r_new = end_r_old + 0.5
        outer_r_new = end_r_new + ligament  # preserves approximate ligament after hole growth

        # Build new plate solid (mid-plane) from external slot/capsule
        plate = (
            cq.Workplane("XY")
            .transformed(offset=(0, 0, zmid))
            .pushPoints([(p1.x, p1.y), (p2.x, p2.y)])
            .circle(outer_r_new)
            .hull()
            .extrude(thickness / 2.0, both=True)
        )

        # Cut updated holes
        for (c, rnew) in new_holes:
            plate = plate.cut(
                cq.Workplane("XY")
                .transformed(offset=(0, 0, zmid))
                .center(c.x, c.y)
                .circle(rnew)
                .extrude(thickness / 2.0 + 5.0, both=True)
            )

        return plate.val()

    def _enlarge_block_features(old_block):
        bb, dx, dy, dz = _bb(old_block)
        zmid = (bb.zmin + bb.zmax) * 0.5
        thick = dz

        wp_blk = cq.Workplane(obj=old_block)
        side_face = _largest_face(wp_blk, ">Z")
        if side_face is None:
            print("Block: could not find >Z face; leaving unchanged")
            return old_block

        inner_wires = _inner_wires_from_face(side_face)

        circle_edges = []  # list of circle edges (full circle) for fixed holes
        slot_end_pairs = []  # list of (c1, c2, r) for slots

        for w in inner_wires:
            edges = list(w.Edges())
            circ = []
            for e in edges:
                try:
                    if e.geomType() == "CIRCLE":
                        circ.append(e)
                except Exception:
                    pass

            # fixed round hole: typically a single circular edge
            if len(edges) == 1 and len(circ) == 1:
                circle_edges.append(circ[0])
                continue

            # slot: typically 2 circular arc edges + 2 lines (but can be split)
            if len(circ) == 2:
                try:
                    c1 = circ[0].Center()
                    c2 = circ[1].Center()
                    r = float(circ[0].radius())
                    slot_end_pairs.append((cq.Vector(c1.x, c1.y, c1.z), cq.Vector(c2.x, c2.y, c2.z), r))
                except Exception:
                    pass

        print(f"Block: dims=({dx:.2f},{dy:.2f},{dz:.2f}) fixed_holes={len(circle_edges)} slots={len(slot_end_pairs)}")

        blk = cq.Workplane("XY").newObject([old_block])

        # Enlarge fixed circular hole(s) by +1mm diameter
        for e in circle_edges:
            try:
                c = e.Center()
                rnew = float(e.radius()) + 0.5
                blk = blk.cut(
                    cq.Workplane("XY")
                    .transformed(offset=(0, 0, zmid))
                    .center(c.x, c.y)
                    .circle(rnew)
                    .extrude(thick / 2.0 + 10.0, both=True)
                )
            except Exception:
                pass

        # Enlarge slot width by +1mm: increase end-arc radius by +0.5 (capsule cut)
        for (c1, c2, r) in slot_end_pairs:
            try:
                rnew = r + 0.5
                blk = blk.cut(
                    cq.Workplane("XY")
                    .transformed(offset=(0, 0, zmid))
                    .pushPoints([(c1.x, c1.y), (c2.x, c2.y)])
                    .circle(rnew)
                    .hull()
                    .extrude(thick / 2.0 + 10.0, both=True)
                )
            except Exception:
                pass

        return blk.val()

    def _rebuild_simple_cylinder_like(old_cyl, extra_radius=0.5):
        bb, dx, dy, dz = _bb(old_cyl)
        xmid = (bb.xmin + bb.xmax) * 0.5
        ymid = (bb.ymin + bb.ymax) * 0.5
        zmid = (bb.zmin + bb.zmax) * 0.5

        r_old = min(dx, dy) * 0.5
        r_new = r_old + extra_radius
        length = dz

        cyl = (
            cq.Workplane("XY")
            .transformed(offset=(0, 0, zmid))
            .center(xmid, ymid)
            .circle(r_new)
            .extrude(length / 2.0, both=True)
            .val()
        )
        return cyl

    new_solids = []
    counts = {"plate": 0, "block": 0, "pin_long": 0, "pin_short": 0}

    for idx, s in enumerate(solids):
        kind = _classify(s)
        counts[kind] = counts.get(kind, 0) + 1
        bb, dx, dy, dz = _bb(s)
        print(f"Solid[{idx}]: kind={kind} dims=({dx:.2f},{dy:.2f},{dz:.2f})")

        if kind == "plate":
            new_solids.append(_rebuild_plate_from_old(s))
        elif kind in ("pin_long", "pin_short"):
            # Increase OD by +1mm diameter => +0.5mm radius
            new_solids.append(_rebuild_simple_cylinder_like(s, extra_radius=0.5))
        else:
            new_solids.append(_enlarge_block_features(s))

    print("Classification counts:", counts)

    return cq.Compound.makeCompound(new_solids)
