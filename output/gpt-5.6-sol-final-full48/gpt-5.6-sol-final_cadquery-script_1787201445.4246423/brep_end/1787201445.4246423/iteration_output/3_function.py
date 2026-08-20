def my_cad_function(args):
    import os
    import math
    import statistics
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    source = imported.val() if hasattr(imported, "val") else imported
    source_bb = source.BoundingBox()

    # Select a Z section through the straight portions of both perimeter walls.
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
        common_min = max(interval[0] for interval in wall_intervals)
        common_max = min(interval[1] for interval in wall_intervals)
    else:
        common_min = source_bb.zmin
        common_max = source_bb.zmax

    if common_max > common_min + 1.0e-5:
        section_z = 0.5 * (common_min + common_max)
    else:
        section_z = source_bb.zmin + 0.5 * source_bb.zlen

    section = cq.Workplane("XY").newObject([source]).section(height=section_z)
    wires = [wire for wire in section.wires().vals() if wire.IsClosed()]
    if len(wires) < 2:
        raise ValueError("Could not recover the outer and inner footprint loops")

    wires.sort(
        key=lambda wire: wire.BoundingBox().xlen * wire.BoundingBox().ylen,
        reverse=True,
    )
    outer_wire, inner_wire = wires[0], wires[1]
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

    def footprint_corner_radius(wire, fallback):
        radii = []
        for edge in wire.Edges():
            try:
                if edge.geomType() == "CIRCLE":
                    radius = float(edge.radius())
                    if radius > 1.0e-4:
                        radii.append(radius)
            except Exception:
                pass
        return float(statistics.median(radii)) if radii else float(fallback)

    outer_r = footprint_corner_radius(outer_wire, 63.0)
    inner_r = footprint_corner_radius(inner_wire, 50.0)
    outer_r = min(outer_r, 0.499 * outer_w, 0.499 * outer_h)
    inner_r = min(inner_r, 0.499 * inner_w, 0.499 * inner_h)

    # Build an analytic rounded rectangle without relying on fillet2D, which is
    # unavailable in the CadQuery version used by the execution environment.
    def rounded_rectangle(w, h, r, origin_z):
        hw = 0.5 * w
        hh = 0.5 * h
        s = r / math.sqrt(2.0)
        return (
            cq.Workplane("XY", origin=(cx, cy, origin_z))
            .moveTo(-hw + r, -hh)
            .lineTo(hw - r, -hh)
            .threePointArc((hw - r + s, -hh + r - s), (hw, -hh + r))
            .lineTo(hw, hh - r)
            .threePointArc((hw - r + s, hh - r + s), (hw - r, hh))
            .lineTo(-hw + r, hh)
            .threePointArc((-hw + r - s, hh - r + s), (-hw, hh - r))
            .lineTo(-hw, -hh + r)
            .threePointArc((-hw + r - s, -hh + r - s), (-hw + r, -hh))
            .close()
        )

    outer_solid = rounded_rectangle(outer_w, outer_h, outer_r, zmin).extrude(depth).val()

    cutter_margin = max(1.0, 0.1 * depth)
    inner_cutter = (
        rounded_rectangle(inner_w, inner_h, inner_r, zmin - cutter_margin)
        .extrude(depth + 2.0 * cutter_margin)
        .val()
    )

    sharp_frame = outer_solid.cut(inner_cutter).clean()
    if not sharp_frame.isValid():
        raise ValueError("The reconstructed sharp annular frame is invalid")

    # The model data identifies the repeated smaller profile radii as R2 and
    # the oversized rear-outer profile radius as R10. Apply R2 to every axial
    # perimeter edge while retaining the R63/R50 plan-view corner paths.
    target_radius = 2.0
    ztol = max(1.0e-5, depth * 1.0e-6)

    def end_edges(solid, end_z, loop_kind=None):
        selected = []
        for edge in solid.Edges():
            bb = edge.BoundingBox()
            if bb.zlen > 10.0 * ztol:
                continue
            if abs(edge.Center().z - end_z) > 20.0 * ztol:
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

    # OCC can be sensitive to filleting concave and convex loops together, so
    # try equivalent grouping orders and retain the first valid result.
    strategies = [
        [(zmin, None), (zmax, None)],
        [(zmax, None), (zmin, None)],
        [(zmin, "outer"), (zmax, "outer"), (zmin, "inner"), (zmax, "inner")],
        [(zmin, "inner"), (zmax, "inner"), (zmin, "outer"), (zmax, "outer")],
        [(zmin, "outer"), (zmin, "inner"), (zmax, "outer"), (zmax, "inner")],
    ]

    result = None
    errors = []
    for strategy in strategies:
        candidate = sharp_frame
        try:
            for end_z, loop_kind in strategy:
                edges = end_edges(candidate, end_z, loop_kind)
                if not edges:
                    raise ValueError("No matching axial perimeter edges were found")
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
    print("Uniform cross-sectional profile radius:", target_radius)
    print("Result valid:", result.isValid())

    return cq.Workplane("XY").newObject([result])