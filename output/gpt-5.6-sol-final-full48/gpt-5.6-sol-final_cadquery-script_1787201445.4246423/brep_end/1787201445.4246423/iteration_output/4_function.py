def my_cad_function(args):
    import os
    import math
    import statistics
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    source = imported.val() if hasattr(imported, "val") else imported
    source_bb = source.BoundingBox()

    # Recover the unchanging inner and outer wall footprints from a section
    # passing through the straight portions of both perimeter walls.
    wall_intervals = []
    for face in source.Faces():
        try:
            if face.geomType() == "PLANE":
                normal = face.normalAt()
                bb = face.BoundingBox()
                if abs(normal.z) < 0.05 and bb.zlen > 1.0e-5:
                    wall_intervals.append((bb.zmin, bb.zmax))
        except Exception:
            pass

    if wall_intervals:
        section_min = max(item[0] for item in wall_intervals)
        section_max = min(item[1] for item in wall_intervals)
    else:
        section_min = source_bb.zmin
        section_max = source_bb.zmax

    if section_max > section_min + 1.0e-4:
        section_z = 0.5 * (section_min + section_max)
    else:
        section_z = source_bb.zmin + 0.5 * source_bb.zlen

    section = cq.Workplane("XY").newObject([source]).section(height=section_z)
    wires = [w for w in section.wires().vals() if w.IsClosed()]
    if len(wires) < 2:
        raise ValueError("Could not recover the two closed frame footprints")

    wires.sort(
        key=lambda w: w.BoundingBox().xlen * w.BoundingBox().ylen,
        reverse=True,
    )
    outer_wire = wires[0]
    inner_wire = wires[1]
    obb = outer_wire.BoundingBox()
    ibb = inner_wire.BoundingBox()

    outer_w = obb.xlen
    outer_h = obb.ylen
    inner_w = ibb.xlen
    inner_h = ibb.ylen
    cx = 0.5 * (obb.xmin + obb.xmax)
    cy = 0.5 * (obb.ymin + obb.ymax)
    zmin = source_bb.zmin
    zmax = source_bb.zmax
    depth = zmax - zmin

    def loop_radius(wire, fallback):
        values = []
        for edge in wire.Edges():
            try:
                if edge.geomType() == "CIRCLE":
                    radius = float(edge.radius())
                    if radius > 1.0e-4:
                        values.append(radius)
            except Exception:
                pass
        return float(statistics.median(values)) if values else float(fallback)

    outer_r = min(loop_radius(outer_wire, 63.0), 0.499 * outer_w, 0.499 * outer_h)
    inner_r = min(loop_radius(inner_wire, 50.0), 0.499 * inner_w, 0.499 * inner_h)

    def rounded_rectangle(width, height, radius, z):
        hw = 0.5 * width
        hh = 0.5 * height
        s = radius / math.sqrt(2.0)
        return (
            cq.Workplane("XY", origin=(cx, cy, z))
            .moveTo(-hw + radius, -hh)
            .lineTo(hw - radius, -hh)
            .threePointArc((hw - radius + s, -hh + radius - s),
                           (hw, -hh + radius))
            .lineTo(hw, hh - radius)
            .threePointArc((hw - radius + s, hh - radius + s),
                           (hw - radius, hh))
            .lineTo(-hw + radius, hh)
            .threePointArc((-hw + radius - s, hh - radius + s),
                           (-hw, hh - radius))
            .lineTo(-hw, -hh + radius)
            .threePointArc((-hw + radius - s, -hh + radius - s),
                           (-hw + radius, -hh))
            .close()
        )

    outer = rounded_rectangle(outer_w, outer_h, outer_r, zmin).extrude(depth).val()
    margin = max(1.0, 0.1 * depth)
    inner = (
        rounded_rectangle(inner_w, inner_h, inner_r, zmin - margin)
        .extrude(depth + 2.0 * margin)
        .val()
    )
    sharp_frame = outer.cut(inner).clean()
    if not sharp_frame.isValid():
        raise ValueError("Reconstructed annular frame is invalid")

    target_radius = 2.0

    def same_edge(a, b):
        try:
            return bool(a.wrapped.IsSame(b.wrapped))
        except Exception:
            return a == b

    def planar_end_edges(solid, side=None):
        selected = []
        for face in solid.Faces():
            try:
                if face.geomType() != "PLANE":
                    continue
                normal = face.normalAt()
                if abs(normal.z) < 0.99:
                    continue
                if side == "top" and normal.z < 0.0:
                    continue
                if side == "bottom" and normal.z > 0.0:
                    continue
                for edge in face.Edges():
                    if not any(same_edge(edge, old) for old in selected):
                        selected.append(edge)
            except Exception:
                pass
        return selected

    # Fillet all four axial profile corners in one operation. This avoids the
    # prior failure caused by searching for already-displaced edges after an
    # earlier fillet operation.
    errors = []
    result = None
    all_edges = planar_end_edges(sharp_frame)
    try:
        if not all_edges:
            raise ValueError("No end-face boundary edges were found")
        candidate = sharp_frame.fillet(target_radius, all_edges).clean()
        if not candidate.isValid():
            raise ValueError("Simultaneous profile fillet produced an invalid solid")
        result = candidate
    except Exception as exc:
        errors.append("simultaneous: " + str(exc))

    # Fallback for OCC builds that prefer the two axial ends to be processed
    # separately. Face-normal selection remains valid after the first fillet.
    if result is None:
        for order in (("top", "bottom"), ("bottom", "top")):
            try:
                candidate = sharp_frame
                for side in order:
                    edges = planar_end_edges(candidate, side)
                    if not edges:
                        raise ValueError("No %s end edges found" % side)
                    candidate = candidate.fillet(target_radius, edges).clean()
                if not candidate.isValid():
                    raise ValueError("Sequential profile fillets produced an invalid solid")
                result = candidate
                break
            except Exception as exc:
                errors.append("%s: %s" % (" then ".join(order), str(exc)))

    if result is None:
        raise ValueError("Uniform R2 profile reconstruction failed: " + " | ".join(errors))

    print("Source envelope:", source_bb.xlen, source_bb.ylen, source_bb.zlen)
    print("Recovered footprints:", outer_w, outer_h, inner_w, inner_h)
    print("Preserved plan-view radii:", outer_r, inner_r)
    print("Profile radii changed to uniform R2")
    print("Selected end edges:", len(all_edges))
    print("Result valid:", result.isValid())

    return cq.Workplane("XY").newObject([result])