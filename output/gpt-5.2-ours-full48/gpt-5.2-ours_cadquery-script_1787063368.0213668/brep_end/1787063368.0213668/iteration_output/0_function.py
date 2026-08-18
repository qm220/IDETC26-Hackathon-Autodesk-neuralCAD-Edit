def my_cad_function(args):
    import cadquery as cq
    import os
    import math

    input_file = args.get("input_file", None)
    if not input_file or not os.path.exists(os.path.expanduser(input_file)):
        raise ValueError("No valid args['input_file'] STEP path provided")
    input_file = os.path.expanduser(input_file)

    imp = cq.importers.importStep(input_file)

    # Get a CQ Shape
    base_shape = imp.val() if hasattr(imp, "val") else imp

    # Collect solids
    solids = []
    try:
        solids = list(base_shape.Solids())
    except Exception:
        # sometimes base_shape can be a Workplane/Compound wrapper
        try:
            solids = list(imp.val().Solids())
        except Exception as e:
            raise RuntimeError(f"Could not enumerate solids: {e}")

    print(f"Loaded STEP: {input_file}")
    print(f"Total solids found: {len(solids)}")

    def _bb_dims(s):
        bb = s.BoundingBox()
        return bb, bb.xlen, bb.ylen, bb.zlen

    def _classify(s):
        bb, dx, dy, dz = _bb_dims(s)
        a = sorted([dx, dy, dz])
        # thin plate: one dimension very small
        if a[0] < 3.5 and a[2] > 20:
            return "plate"
        # long pin: two small dims, one very long
        if max(dx, dy) < 9 and dz > 25:
            return "pin_long"
        # short spacer: generally small cylinder
        if max(dx, dy) < 9 and dz <= 10:
            return "pin_short"
        return "block"

    def _inner_wires_from_face(face):
        outer = face.outerWire()
        inners = []
        for w in face.Wires():
            try:
                if not w.isSame(outer):
                    inners.append(w)
            except Exception:
                # fallback: compare hash codes
                if w.hashCode() != outer.hashCode():
                    inners.append(w)
        return inners

    def _wire_is_circle(wire):
        edges = list(wire.Edges())
        if len(edges) != 1:
            return False
        try:
            return edges[0].geomType() == "CIRCLE"
        except Exception:
            # if geomType not available, assume false
            return False

    def _edge_points(edge, n=20):
        # Return list[cq.Vector]
        try:
            pts = edge.discretize(n)
            # pts may be list[Vector] already
            out = []
            for p in pts:
                if isinstance(p, cq.Vector):
                    out.append(p)
                else:
                    # gp_Pnt
                    out.append(cq.Vector(p.X(), p.Y(), p.Z()))
            return out
        except Exception:
            pts = []
            try:
                pts.append(edge.startPoint())
                pts.append(edge.midPoint())
                pts.append(edge.endPoint())
                return pts
            except Exception:
                return []

    def _max_halfwidth_about_centerline(outer_wire, p1, p2):
        # Measure max distance from centerline (p1-p2) to outer profile in XY
        v = cq.Vector(p2.x - p1.x, p2.y - p1.y, 0)
        L = math.hypot(v.x, v.y)
        if L < 1e-6:
            return None
        xdir = cq.Vector(v.x / L, v.y / L, 0)
        ydir = cq.Vector(-xdir.y, xdir.x, 0)
        origin = cq.Vector((p1.x + p2.x) * 0.5, (p1.y + p2.y) * 0.5, 0)

        max_abs_y = 0.0
        for e in outer_wire.Edges():
            for pt in _edge_points(e, n=25):
                vv = cq.Vector(pt.x - origin.x, pt.y - origin.y, 0)
                y = vv.dot(ydir)
                max_abs_y = max(max_abs_y, abs(y))
        return max_abs_y

    def _rebuild_plate_from_old(old_plate):
        bb, dx, dy, dz = _bb_dims(old_plate)
        zmid = (bb.zmin + bb.zmax) * 0.5
        thickness = dz

        wp_old = cq.Workplane(obj=old_plate)
        # Use +Z face for hole extraction (has through-hole loops)
        top_face = wp_old.faces(">Z").sortByArea().first().val()
        outer_wire = top_face.outerWire()
        inner_wires = _inner_wires_from_face(top_face)

        holes = []  # (centerVector, radius)
        for w in inner_wires:
            edges = list(w.Edges())
            if len(edges) == 1:
                e = edges[0]
                try:
                    if e.geomType() == "CIRCLE":
                        c = e.Center()
                        r = e.radius()
                        holes.append((cq.Vector(c.x, c.y, c.z), float(r)))
                except Exception:
                    pass

        print(f"Plate: bb=({dx:.2f},{dy:.2f},{dz:.2f}) zmid={zmid:.3f} holes_found={len(holes)}")
        if len(holes) < 3:
            print("  WARNING: plate hole extraction failed; leaving plate unchanged")
            return old_plate

        # Identify end holes as farthest pair
        centers = [h[0] for h in holes]
        radii = [h[1] for h in holes]

        max_d = -1
        end_i, end_j = 0, 1
        for i in range(len(centers)):
            for j in range(i + 1, len(centers)):
                d = centers[i].sub(centers[j]).Length
                if d > max_d:
                    max_d = d
                    end_i, end_j = i, j

        p1 = centers[end_i]
        p2 = centers[end_j]

        # New hole radii: +0.5mm radius (=> +1mm diameter)
        new_holes = []
        for (c, r) in holes:
            new_holes.append((c, r + 0.5))

        # Determine outer slot radius from existing outer perimeter width (max half width)
        end_r_old = radii[end_i]
        half_w = _max_halfwidth_about_centerline(outer_wire, p1, p2)
        if half_w is None:
            half_w = end_r_old + 3.0

        ligament = max(1.0, half_w - end_r_old)
        end_r_new = end_r_old + 0.5
        outer_r_new = end_r_new + ligament  # keeps ligament approximately constant

        # Build new external profile as a capsule (hull of two circles) centered at end holes
        plate_wp = (
            cq.Workplane("XY")
            .workplane(offset=zmid)
            .pushPoints([(p1.x, p1.y), (p2.x, p2.y)])
            .circle(outer_r_new)
            .hull()
            .extrude(thickness / 2.0, both=True)
        )

        # Cut the 3 holes (end + center), each diameter +1mm
        for (c, rnew) in new_holes:
            cutter = (
                cq.Workplane("XY")
                .workplane(offset=zmid)
                .center(c.x, c.y)
                .circle(rnew)
                .extrude(thickness / 2.0 + 2.0, both=True)
            )
            plate_wp = plate_wp.cut(cutter)

        return plate_wp.val()

    def _enlarge_block_features(old_block):
        bb, dx, dy, dz = _bb_dims(old_block)
        zmid = (bb.zmin + bb.zmax) * 0.5
        thick = dz

        wp_blk = cq.Workplane(obj=old_block)
        side_face = wp_blk.faces(">Z").sortByArea().first().val()
        inner_wires = _inner_wires_from_face(side_face)

        circle_wires = []
        slot_wires = []
        for w in inner_wires:
            edges = list(w.Edges())
            n_circ = 0
            for e in edges:
                try:
                    if e.geomType() == "CIRCLE":
                        n_circ += 1
                except Exception:
                    pass
            if len(edges) == 1 and n_circ == 1:
                circle_wires.append(w)
            elif n_circ == 2:
                slot_wires.append(w)

        print(f"Block: bb=({dx:.2f},{dy:.2f},{dz:.2f}) circle_wires={len(circle_wires)} slot_wires={len(slot_wires)}")

        blk_wp = cq.Workplane("XY").newObject([old_block])

        # Enlarge fixed circular pivot hole(s): +1mm diameter
        for w in circle_wires:
            e = list(w.Edges())[0]
            try:
                c = e.Center()
                r = float(e.radius())
                rnew = r + 0.5
                cutter = (
                    cq.Workplane("XY")
                    .workplane(offset=zmid)
                    .center(c.x, c.y)
                    .circle(rnew)
                    .extrude(thick / 2.0 + 5.0, both=True)
                )
                blk_wp = blk_wp.cut(cutter)
            except Exception:
                pass

        # Enlarge slot: +1mm width (implemented by increasing end-arc radius by +0.5)
        for w in slot_wires:
            edges = list(w.Edges())
            circ_edges = []
            for e in edges:
                try:
                    if e.geomType() == "CIRCLE":
                        circ_edges.append(e)
                except Exception:
                    pass
            if len(circ_edges) != 2:
                continue
            try:
                c1 = circ_edges[0].Center()
                c2 = circ_edges[1].Center()
                r = float(circ_edges[0].radius())
                rnew = r + 0.5
                cutter = (
                    cq.Workplane("XY")
                    .workplane(offset=zmid)
                    .pushPoints([(c1.x, c1.y), (c2.x, c2.y)])
                    .circle(rnew)
                    .hull()
                    .extrude(thick / 2.0 + 5.0, both=True)
                )
                blk_wp = blk_wp.cut(cutter)
            except Exception:
                pass

        return blk_wp.val()

    def _rebuild_cylinder_like(old_cyl, extra_radius=0.5):
        bb, dx, dy, dz = _bb_dims(old_cyl)
        xmid = (bb.xmin + bb.xmax) * 0.5
        ymid = (bb.ymin + bb.ymax) * 0.5
        zmid = (bb.zmin + bb.zmax) * 0.5

        r_old = min(dx, dy) * 0.5
        r_new = r_old + extra_radius
        length = dz

        cyl = (
            cq.Workplane("XY")
            .workplane(offset=zmid)
            .center(xmid, ymid)
            .circle(r_new)
            .extrude(length / 2.0, both=True)
            .val()
        )
        return cyl

    # Process all solids
    new_solids = []
    counts = {"plate": 0, "block": 0, "pin_long": 0, "pin_short": 0}

    for idx, s in enumerate(solids):
        kind = _classify(s)
        counts[kind] = counts.get(kind, 0) + 1
        bb, dx, dy, dz = _bb_dims(s)
        print(f"Solid[{idx}]: kind={kind} dims=({dx:.2f},{dy:.2f},{dz:.2f})")

        if kind == "plate":
            new_solids.append(_rebuild_plate_from_old(s))
        elif kind == "pin_long" or kind == "pin_short":
            # Increase OD by 1mm (radius +0.5)
            new_solids.append(_rebuild_cylinder_like(s, extra_radius=0.5))
        else:
            # blocks: enlarge fixed hole + slot width by 1mm
            new_solids.append(_enlarge_block_features(s))

    print("Classification counts:", counts)

    # Return as compound to preserve multi-body structure
    comp = cq.Compound.makeCompound(new_solids)
    return comp
