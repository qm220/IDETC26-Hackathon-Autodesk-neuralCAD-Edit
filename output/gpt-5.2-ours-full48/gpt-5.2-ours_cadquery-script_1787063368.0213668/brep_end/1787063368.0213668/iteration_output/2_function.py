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
        # plates: thin in Z (~2mm) but long in X/Y
        if a[0] < 3.5 and a[2] > 20:
            return "plate"
        # pins: small XY, long Z
        if max(dx, dy) < 9 and dz > 25:
            return "pin_long"
        if max(dx, dy) < 9 and dz <= 12:
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

    def _capsule_wire_2d(wp, p1xy, p2xy, R):
        """Create a 2D capsule (slot) wire from two end centers and radius R on the given Workplane."""
        (x1, y1) = p1xy
        (x2, y2) = p2xy
        dx, dy = (x2 - x1), (y2 - y1)
        L = math.hypot(dx, dy)
        if L < 1e-8:
            return wp.center(x1, y1).circle(R)

        ux, uy = dx / L, dy / L
        vx, vy = -uy, ux  # left perp

        Ax, Ay = x1 + R * vx, y1 + R * vy
        Bx, By = x2 + R * vx, y2 + R * vy
        Cx, Cy = x2 - R * vx, y2 - R * vy
        Dx, Dy = x1 - R * vx, y1 - R * vy

        # midpoints for semicircle arcs (bulge direction)
        M2x, M2y = x2 + R * ux, y2 + R * uy
        M1x, M1y = x1 - R * ux, y1 - R * uy

        return (
            wp.moveTo(Ax, Ay)
              .lineTo(Bx, By)
              .threePointArc((M2x, M2y), (Cx, Cy))
              .lineTo(Dx, Dy)
              .threePointArc((M1x, M1y), (Ax, Ay))
              .close()
        )

    def _extract_circular_holes_from_face(face, min_count=3):
        """Returns list of (centerVector, radius) for circular inner wires on the face."""
        inner_wires = _inner_wires_from_face(face)
        holes = []
        for w in inner_wires:
            edges = list(w.Edges())
            if len(edges) != 1:
                continue
            e = edges[0]
            try:
                if e.geomType() == "CIRCLE":
                    c = e.Center()
                    r = float(e.radius())
                    holes.append((cq.Vector(c.x, c.y, c.z), r))
            except Exception:
                continue
        if len(holes) < min_count:
            return []
        return holes

    def _rebuild_plate_from_old(old_plate):
        bb, dx, dy, dz = _bb(old_plate)
        zmid = (bb.zmin + bb.zmax) * 0.5
        thickness = dz

        wp_old = cq.Workplane(obj=old_plate)
        face = _largest_face(wp_old, ">Z")
        if face is None:
            face = _largest_face(wp_old, "<Z")
        if face is None:
            print("  Plate: could not find large planar face; leaving unchanged")
            return old_plate

        outer_wire = face.outerWire()
        holes = _extract_circular_holes_from_face(face, min_count=3)

        print(f"Plate: dims=({dx:.2f},{dy:.2f},{dz:.2f}) zmid={zmid:.3f} holes_found={len(holes)}")
        if len(holes) < 3:
            print("  WARNING: expected 3 circular holes on plate face; leaving plate unchanged")
            return old_plate

        centers = [h[0] for h in holes]
        radii = [h[1] for h in holes]

        # end holes = farthest pair
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

        # Actions 1 & 3: outer profile becomes capsule (slot) using end-hole centers.
        # Infer ligament from old plate outline vs old end-hole radius.
        end_r_old = radii[end_i]
        half_w_old = _max_halfwidth_about_centerline(outer_wire, p1, p2)
        if half_w_old is None:
            half_w_old = end_r_old + 3.0
        ligament = max(1.0, half_w_old - end_r_old)

        end_r_new = end_r_old + 0.5
        outer_r_new = end_r_new + ligament  # preserve ligament after hole growth

        wp = cq.Workplane("XY").transformed(offset=(0, 0, zmid))
        wp = _capsule_wire_2d(wp, (p1.x, p1.y), (p2.x, p2.y), outer_r_new)
        plate = wp.extrude(thickness / 2.0, both=True)

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

    def _cluster_by_center(circles, tol=1e-3):
        """Group circle edges by center (x,y) within tolerance; return list of groups."""
        groups = []
        for e in circles:
            try:
                c = e.Center()
                cx, cy = float(c.x), float(c.y)
            except Exception:
                continue
            placed = False
            for g in groups:
                (gx, gy) = g["center"]
                if (cx - gx) ** 2 + (cy - gy) ** 2 <= tol ** 2:
                    g["edges"].append(e)
                    placed = True
                    break
            if not placed:
                groups.append({"center": (cx, cy), "edges": [e]})
        return groups

    def _enlarge_block_features(old_block):
        bb, dx, dy, dz = _bb(old_block)
        zmid = (bb.zmin + bb.zmax) * 0.5
        thick = dz

        wp_blk = cq.Workplane(obj=old_block)
        face = _largest_face(wp_blk, ">Z")
        if face is None:
            face = _largest_face(wp_blk, "<Z")
        if face is None:
            print("Block: could not find +/-Z face; leaving unchanged")
            return old_block

        inner_wires = _inner_wires_from_face(face)
        fixed_holes = []  # (cx,cy,r)
        slots = []       # (c1x,c1y,c2x,c2y,r)

        for w in inner_wires:
            edges = list(w.Edges())
            circle_edges = []
            for e in edges:
                try:
                    if e.geomType() == "CIRCLE":
                        circle_edges.append(e)
                except Exception:
                    pass

            # Fixed hole: often a single full circle edge.
            if len(edges) == 1 and len(circle_edges) == 1:
                try:
                    e = circle_edges[0]
                    c = e.Center()
                    fixed_holes.append((float(c.x), float(c.y), float(e.radius())))
                except Exception:
                    pass
                continue

            # Slot: look for two distinct circle centers in the wire
            if len(circle_edges) >= 2:
                groups = _cluster_by_center(circle_edges, tol=1e-3)
                if len(groups) == 2:
                    try:
                        (c1x, c1y) = groups[0]["center"]
                        (c2x, c2y) = groups[1]["center"]
                        r = float(groups[0]["edges"][0].radius())
                        slots.append((c1x, c1y, c2x, c2y, r))
                    except Exception:
                        pass

        print(f"Block: dims=({dx:.2f},{dy:.2f},{dz:.2f}) fixed_holes={len(fixed_holes)} slots={len(slots)}")

        blk = cq.Workplane("XY").newObject([old_block])

        # Enlarge fixed circular holes by +1mm diameter => +0.5 radius
        for (cx, cy, r) in fixed_holes:
            rnew = r + 0.5
            blk = blk.cut(
                cq.Workplane("XY")
                .transformed(offset=(0, 0, zmid))
                .center(cx, cy)
                .circle(rnew)
                .extrude(thick / 2.0 + 10.0, both=True)
            )

        # Enlarge slot width by +1mm (end radius +0.5) using capsule cut
        for (c1x, c1y, c2x, c2y, r) in slots:
            rnew = r + 0.5
            wp = cq.Workplane("XY").transformed(offset=(0, 0, zmid))
            wp = _capsule_wire_2d(wp, (c1x, c1y), (c2x, c2y), rnew)
            blk = blk.cut(wp.extrude(thick / 2.0 + 10.0, both=True))

        return blk.val()

    def _rebuild_simple_cylinder_like(old_cyl, extra_radius=0.5):
        # assumes cylinder axis approximately along Z
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
