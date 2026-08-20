def my_cad_function(args):
    import os
    import statistics
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    source = imported.val() if hasattr(imported, "val") else imported
    source_bb = source.BoundingBox()

    # Find a section lying in the straight portions of the perimeter walls.
    wall_intervals = []
    for face in source.Faces():
        try:
            if face.geomType() == "PLANE":
                n = face.normalAt()
                bb = face.BoundingBox()
                if abs(n.z) < 0.05 and bb.zlen > 1.0e-5:
                    wall_intervals.append((bb.zmin, bb.zmax))
        except Exception:
            pass

    if wall_intervals:
        common_min = max(v[0] for v in wall_intervals)
        common_max = min(v[1] for v in wall_intervals)
    else:
        common_min = source_bb.zmin
        common_max = source_bb.zmax

    if common_max > common_min + 1.0e-5:
        section_z = 0.5 * (common_min + common_max)
    else:
        section_z = source_bb.zmin + 0.5 * source_bb.zlen

    section = cq.Workplane("XY").newObject([source]).section(height=section_z)
    wires = [w for w in section.wires().vals() if w.IsClosed()]
    if len(wires) < 2:
        raise ValueError("Could not recover the two rounded-rectangle footprint loops")

    wires.sort(
        key=lambda w: w.BoundingBox().xlen * w.BoundingBox().ylen,
        reverse=True,
    )
    outer_wire, inner_wire = wires[0], wires[1]
    obb = outer_wire.BoundingBox()
    ibb = inner_wire.BoundingBox()

    outer_w, outer_h = obb.xlen, obb.ylen
    inner_w, inner_h = ibb.xlen, ibb.ylen
    cx = 0.5 * (obb.xmin + obb.xmax)
    cy = 0.5 * (obb.ymin + obb.ymax)
    zmin, zmax = source_bb.zmin, source_bb.zmax
    depth = zmax - zmin

    # Recover the plan-view corner radii. Rebuilding clean analytic rounded
    # rectangles avoids section-edge tolerances that caused the previous
    # all-at-once fillet operation to fail.
    def footprint_corner_radius(wire, fallback):
        radii = []
        for edge in wire.Edges():
            try:
                if edge.geomType() == "CIRCLE":
                    r = float(edge.radius())
                    if r > 1.0e-4:
                        radii.append(r)
            except Exception:
                pass
        if not radii:
            return fallback
        radii.sort()
        return float(statistics.median(radii))

    outer_r = footprint_corner_radius(outer_wire, 63.0)
    inner_r = footprint_corner_radius(inner_wire, 50.0)
    outer_r = min(outer_r, 0.499 * outer_w, 0.499 * outer_h)
    inner_r = min(inner_r, 0.499 * inner_w, 0.499 * inner_h)

    outer_solid = (
        cq.Workplane("XY", origin=(cx, cy, zmin))
        .rect(outer_w, outer_h)
        .vertices()
        .fillet2D(outer_r)
        .extrude(depth)
        .val()
    )

    # Extend the cutter beyond both seating planes for a reliable through-hole.
    cutter_margin = max(1.0, 0.1 * depth)
    inner_cutter = (
        cq.Workplane("XY", origin=(cx, cy, zmin - cutter_margin))
        .rect(inner_w, inner_h)
        .vertices()
        .fillet2D(inner_r)
        .extrude(depth + 2.0 * cutter_margin)
        .val()
    )

    sharp_frame = outer_solid.cut(inner_cutter).clean()
    if not sharp_frame.isValid():
        raise ValueError("The reconstructed sharp annular frame is invalid")

    target_radius = 2.0
    ztol = max(1.0e-5, depth * 1.0e-6)

    def end_edges(solid, end_z, loop_kind=None):
        selected = []
        for edge in solid.Edges():
            bb = edge.BoundingBox()
            if bb.zlen > 10.0 * ztol or abs(edge.Center().z - end_z) > 20.0 * ztol:
                continue

            if loop_kind is None:
                selected.append(edge)
                continue

            ex = max(abs(bb.xmin - cx), abs(bb.xmax - cx))
            ey = max(abs(bb.ymin - cy), abs(bb.ymax - cy))
            outer_score = min(abs(ex - outer_w / 2.0), abs(ey - outer_h / 2.0))
            inner_score = min(abs(ex - inner_w / 2.0), abs(ey - inner_h / 2.0))

            if loop_kind == "outer" and outer_score < inner_score:
                selected.append(edge)
            elif loop_kind == "inner" and inner_score < outer_score:
                selected.append(edge)
        return selected

    # Try several equivalent filleting orders. OCC can be sensitive to whether
    # concave and convex annular loops are submitted in one operation.
    strategies = [
        [(zmin, None), (zmax, None)],
        [(zmax, None), (zmin, None)],
        [(zmin, "outer"), (zmax, "outer"),
         (zmin, "inner"), (zmax, "inner")],
        [(zmin, "inner"), (zmax, "inner"),
         (zmin, "outer"), (zmax, "outer")],
        [(zmin, "outer"), (zmin, "inner"),
         (zmax, "outer"), (zmax, "inner")],
    ]

    result = None
    errors = []
    for strategy in strategies:
        candidate = sharp_frame
        try:
            for end_z, loop_kind in strategy:
                edges = end_edges(candidate, end_z, loop_kind)
                if not edges:
                    raise ValueError("No matching axial perimeter edges")
                candidate = candidate.fillet(target_radius, edges)
            candidate = candidate.clean()
            if candidate.isValid():
                result = candidate
                break
        except Exception as exc:
            errors.append(str(exc))

    if result is None:
        raise ValueError("Uniform R2 profile filleting failed: " + " | ".join(errors))

    print("Source envelope:", source_bb.xlen, source_bb.ylen, source_bb.zlen)
    print("Recovered footprints:", outer_w, outer_h, inner_w, inner_h)
    print("Preserved plan radii:", outer_r, inner_r)
    print("Replacement profile radius:", target_radius)
    print("Result valid:", result.isValid())

    return cq.Workplane("XY").newObject([result])