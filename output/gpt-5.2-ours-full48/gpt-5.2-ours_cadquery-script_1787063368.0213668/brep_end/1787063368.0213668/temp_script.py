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

    solids = list(base.Solids())
    print(f"Loaded STEP: {input_file}")
    print(f"Total solids found: {len(solids)}")

    def bb_dims(s):
        bb = s.BoundingBox()
        return bb, bb.xlen, bb.ylen, bb.zlen

    def classify(s):
        bb, dx, dy, dz = bb_dims(s)
        a = sorted([dx, dy, dz])
        # plates: thin in Z (~2mm), large in XY
        if a[0] < 3.5 and a[2] > 20:
            return "plate"
        # pins/spacers: small in XY
        if max(dx, dy) < 9 and dz > 25:
            return "pin_long"
        if max(dx, dy) < 9 and dz <= 12:
            return "pin_short"
        return "block"

    def largest_face_on_obj(obj, selector):
        fs = cq.Workplane(obj=obj).faces(selector).vals()
        if not fs:
            return None
        return max(fs, key=lambda f: f.Area())

    def inner_wires(face):
        outer = face.outerWire()
        inn = []
        for w in face.Wires():
            try:
                if not w.isSame(outer):
                    inn.append(w)
            except Exception:
                if w.hashCode() != outer.hashCode():
                    inn.append(w)
        return inn

    def edge_points(edge, n=80):
        pts = []
        try:
            pts = edge.discretize(n)
        except Exception:
            pts = []
        out = []
        if pts:
            for p in pts:
                # cadquery.Vector
                if isinstance(p, cq.Vector):
                    out.append(p)
                    continue
                # tuple/list
                if isinstance(p, (tuple, list)) and len(p) >= 3:
                    out.append(cq.Vector(float(p[0]), float(p[1]), float(p[2])))
                    continue
                # gp_Pnt-like
                try:
                    out.append(cq.Vector(float(p.X()), float(p.Y()), float(p.Z())))
                    continue
                except Exception:
                    pass
        if out:
            return out
        # fallback
        try:
            return [edge.startPoint(), edge.midPoint(), edge.endPoint()]
        except Exception:
            return []

    def extract_circular_holes(face):
        holes = []
        for w in inner_wires(face):
            edges = list(w.Edges())
            if len(edges) != 1:
                continue
            e = edges[0]
            try:
                if e.geomType() == "CIRCLE":
                    c = e.Center()
                    holes.append((cq.Vector(float(c.x), float(c.y), float(c.z)), float(e.radius())))
            except Exception:
                pass
        return holes

    def capsule_wire_2d(wp, p1xy, p2xy, R):
        (x1, y1) = p1xy
        (x2, y2) = p2xy
        dx, dy = (x2 - x1), (y2 - y1)
        L = math.hypot(dx, dy)
        if L < 1e-8:
            return wp.center(x1, y1).circle(R)

        ux, uy = dx / L, dy / L
        vx, vy = -uy, ux

        Ax, Ay = x1 + R * vx, y1 + R * vy
        Bx, By = x2 + R * vx, y2 + R * vy
        Cx, Cy = x2 - R * vx, y2 - R * vy
        Dx, Dy = x1 - R * vx, y1 - R * vy

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

    def max_halfwidth_about_centerline(outer_wire, p1, p2):
        v = cq.Vector(float(p2.x - p1.x), float(p2.y - p1.y), 0.0)
        L = math.hypot(v.x, v.y)
        if L < 1e-9:
            return None
        xdir = cq.Vector(v.x / L, v.y / L, 0.0)
        ydir = cq.Vector(-xdir.y, xdir.x, 0.0)
        origin = cq.Vector((p1.x + p2.x) * 0.5, (p1.y + p2.y) * 0.5, 0.0)

        max_abs_t = 0.0
        npts = 0
        for e in outer_wire.Edges():
            for pt in edge_points(e, n=80):
                npts += 1
                vv = cq.Vector(float(pt.x - origin.x), float(pt.y - origin.y), 0.0)
                t = vv.dot(ydir)
                if abs(t) > max_abs_t:
                    max_abs_t = abs(t)
        if npts == 0:
            return None
        return max_abs_t

    def find_outer_end_radius_from_outer_wire(outer_wire, end_center, tol=0.25):
        # Prefer explicit circular edge on outer boundary concentric with end hole center
        rs = []
        for e in outer_wire.Edges():
            try:
                if e.geomType() != "CIRCLE":
                    continue
                c = e.Center()
                dx = float(c.x - end_center.x)
                dy = float(c.y - end_center.y)
                if dx * dx + dy * dy <= tol * tol:
                    rs.append(float(e.radius()))
            except Exception:
                pass
        if rs:
            return max(rs)

        # Fallback: sampled min distance to outer boundary points
        dmin = None
        for e in outer_wire.Edges():
            for pt in edge_points(e, n=120):
                d = math.hypot(float(pt.x - end_center.x), float(pt.y - end_center.y))
                if dmin is None or d < dmin:
                    dmin = d
        return dmin

    def rebuild_plate(old_plate):
        bb, dx, dy, dz = bb_dims(old_plate)
        zmid = (bb.zmin + bb.zmax) * 0.5
        thickness = dz

        face = largest_face_on_obj(old_plate, ">Z")
        if face is None:
            face = largest_face_on_obj(old_plate, "<Z")
        if face is None:
            print("  Plate: ERROR could not find planar +/-Z face; leaving unchanged")
            return old_plate

        holes = extract_circular_holes(face)
        outer_wire = face.outerWire()

        print(f"Plate(orig): bb=({dx:.2f},{dy:.2f},{dz:.2f}) zmid={zmid:.3f} circular_holes={len(holes)}")
        if len(holes) < 3:
            print("  Plate: WARNING expected >=3 circular holes; leaving unchanged")
            return old_plate

        centers = [h[0] for h in holes]
        radii = [h[1] for h in holes]

        # end holes are farthest pair
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

        # central hole: closest to midpoint
        mid = cq.Vector((p1.x + p2.x) * 0.5, (p1.y + p2.y) * 0.5, (p1.z + p2.z) * 0.5)
        cen_k = None
        cen_dist = 1e99
        for k, c in enumerate(centers):
            if k in (end_i, end_j):
                continue
            d = c.sub(mid).Length
            if d < cen_dist:
                cen_dist = d
                cen_k = k

        end_r_old = float(radii[end_i])
        cen_r_old = float(radii[cen_k]) if cen_k is not None else None

        # Action 2: +1mm diameter -> +0.5 radius for ALL holes
        new_holes = [(c, float(r) + 0.5) for (c, r) in holes]
        end_r_new = end_r_old + 0.5
        cen_r_new = (cen_r_old + 0.5) if cen_r_old is not None else None

        # Action 1: external outline becomes a capsule (long-hole) between end-hole centers
        # Action 3: adjust capsule radius so ligaments do not shrink after hole dia change.
        half_w_old = max_halfwidth_about_centerline(outer_wire, p1, p2)
        end_outer_r_old_1 = find_outer_end_radius_from_outer_wire(outer_wire, p1)
        end_outer_r_old_2 = find_outer_end_radius_from_outer_wire(outer_wire, p2)

        end_outer_r_old = None
        if end_outer_r_old_1 and end_outer_r_old_2:
            end_outer_r_old = 0.5 * (end_outer_r_old_1 + end_outer_r_old_2)
        elif end_outer_r_old_1:
            end_outer_r_old = end_outer_r_old_1
        elif end_outer_r_old_2:
            end_outer_r_old = end_outer_r_old_2

        # Infer old ligament at end holes (prefer end-arc radius)
        if end_outer_r_old is not None and end_outer_r_old > 0:
            ligament_end_old = max(1.0, end_outer_r_old - end_r_old)
        else:
            if half_w_old is None:
                half_w_old = end_r_old + 3.0
            ligament_end_old = max(1.0, half_w_old - end_r_old)

        # Required new capsule radius to keep the same ligament after hole radius increase
        outer_r_new = end_r_new + ligament_end_old  # = (end_r_old+0.5)+ligament

        # Also ensure we don't accidentally shrink width versus old max width
        if half_w_old is not None:
            outer_r_new = max(outer_r_new, float(half_w_old))

        # Ensure at least 1mm margin to central hole too (conservative)
        if cen_r_new is not None:
            outer_r_new = max(outer_r_new, cen_r_new + 1.0)

        # Extra safety: avoid razor-thin strap if inference failed
        outer_r_new = max(outer_r_new, end_r_new + 1.5)

        print(
            f"  Plate: end_r_old={end_r_old:.3f}->end_r_new={end_r_new:.3f} ; "
            f"end_outer_r_old={None if end_outer_r_old is None else round(end_outer_r_old,3)} ; "
            f"half_w_old={None if half_w_old is None else round(half_w_old,3)} ; "
            f"lig_end_old={ligament_end_old:.3f} ; outer_r_new={outer_r_new:.3f}"
        )

        # Build new capsule plate
        wp = cq.Workplane("XY").transformed(offset=(0, 0, zmid))
        wp = capsule_wire_2d(wp, (float(p1.x), float(p1.y)), (float(p2.x), float(p2.y)), float(outer_r_new))
        plate = wp.extrude(thickness / 2.0, both=True)

        # Cut updated holes
        for (c, rnew) in new_holes:
            plate = plate.cut(
                cq.Workplane("XY")
                  .transformed(offset=(0, 0, zmid))
                  .center(float(c.x), float(c.y))
                  .circle(float(rnew))
                  .extrude(thickness / 2.0 + 10.0, both=True)
            )

        # Post-check: re-measure hole radii on rebuilt plate
        f2 = largest_face_on_obj(plate.val(), ">Z")
        if f2 is not None:
            h2 = extract_circular_holes(f2)
            rs = sorted([round(r, 3) for (_, r) in h2])
            print(f"  Plate(new): circular_holes={len(h2)} radii={rs}")

        return plate.val()

    def cluster_by_center(edges, tol=1e-3):
        groups = []
        for e in edges:
            try:
                c = e.Center()
                cx, cy = float(c.x), float(c.y)
            except Exception:
                continue
            placed = False
            for g in groups:
                gx, gy = g["center"]
                if (cx - gx) ** 2 + (cy - gy) ** 2 <= tol ** 2:
                    g["edges"].append(e)
                    placed = True
                    break
            if not placed:
                groups.append({"center": (cx, cy), "edges": [e]})
        return groups

    def enlarge_block(old_block):
        bb, dx, dy, dz = bb_dims(old_block)
        zmid = (bb.zmin + bb.zmax) * 0.5
        thick = dz

        face = largest_face_on_obj(old_block, ">Z")
        if face is None:
            face = largest_face_on_obj(old_block, "<Z")
        if face is None:
            print("Block: ERROR could not find +/-Z face; leaving unchanged")
            return old_block

        fixed_holes = []
        slots = []

        for w in inner_wires(face):
            edges = list(w.Edges())
            circle_edges = []
            for e in edges:
                try:
                    if e.geomType() == "CIRCLE":
                        circle_edges.append(e)
                except Exception:
                    pass

            # fixed hole: single circle edge
            if len(edges) == 1 and len(circle_edges) == 1:
                e = circle_edges[0]
                c = e.Center()
                fixed_holes.append((float(c.x), float(c.y), float(e.radius())))
                continue

            # slot: two circle centers
            if len(circle_edges) >= 2:
                groups = cluster_by_center(circle_edges, tol=1e-3)
                if len(groups) == 2:
                    (c1x, c1y) = groups[0]["center"]
                    (c2x, c2y) = groups[1]["center"]
                    r = float(groups[0]["edges"][0].radius())
                    slots.append((c1x, c1y, c2x, c2y, r))

        print(f"Block(orig): bb=({dx:.2f},{dy:.2f},{dz:.2f}) fixed_holes={len(fixed_holes)} slots={len(slots)}")
        blk = cq.Workplane("XY").newObject([old_block])

        # Action 2: enlarge fixed holes by +1mm diameter
        for (cx, cy, r) in fixed_holes:
            rnew = r + 0.5
            blk = blk.cut(
                cq.Workplane("XY")
                  .transformed(offset=(0, 0, zmid))
                  .center(cx, cy)
                  .circle(rnew)
                  .extrude(thick / 2.0 + 20.0, both=True)
            )

        # Action 2: enlarge slots by +1mm width (end radius +0.5)
        for (c1x, c1y, c2x, c2y, r) in slots:
            rnew = r + 0.5
            wp = cq.Workplane("XY").transformed(offset=(0, 0, zmid))
            wp = capsule_wire_2d(wp, (c1x, c1y), (c2x, c2y), rnew)
            blk = blk.cut(wp.extrude(thick / 2.0 + 20.0, both=True))

        return blk.val()

    def rebuild_pin_as_cylinder(old_pin, extra_radius=0.5):
        bb, dx, dy, dz = bb_dims(old_pin)
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
        bb2, dx2, dy2, dz2 = bb_dims(cyl)
        print(f"  Pin rebuild: r_old={r_old:.3f} -> r_new={r_new:.3f} ; new_bb=({dx2:.2f},{dy2:.2f},{dz2:.2f})")
        return cyl

    new_solids = []
    counts = {"plate": 0, "block": 0, "pin_long": 0, "pin_short": 0}

    for i, s in enumerate(solids):
        k = classify(s)
        counts[k] += 1
        bb, dx, dy, dz = bb_dims(s)
        print(f"Solid[{i}]: kind={k} bb=({dx:.2f},{dy:.2f},{dz:.2f})")

        if k == "plate":
            new_solids.append(rebuild_plate(s))
        elif k in ("pin_long", "pin_short"):
            # Action 2: increase OD +1mm dia
            new_solids.append(rebuild_pin_as_cylinder(s, extra_radius=0.5))
        else:
            # Action 2: enlarge block fixed hole and slot width to match increased pin diameter
            new_solids.append(enlarge_block(s))

    print("Classification counts:", counts)

    out = cq.Compound.makeCompound(new_solids)
    try:
        ss = list(out.Solids())
        print(f"Output solids: {len(ss)}")
    except Exception:
        pass
    return out
