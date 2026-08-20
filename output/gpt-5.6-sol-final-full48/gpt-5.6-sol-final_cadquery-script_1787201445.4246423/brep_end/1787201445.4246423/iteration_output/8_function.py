def my_cad_function(args):
    import os
    import math
    import statistics
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)

    solids = [s for s in imported.solids().vals() if s is not None and not s.isNull()]
    if not solids:
        raise ValueError("The input STEP file contains no solid")

    source = max(solids, key=lambda s: abs(s.Volume()))
    source_bb = source.BoundingBox()

    # Find a Z level passing through the unchanged straight wall region rather
    # than through either end's profile fillets.
    vertical_intervals = []
    for face in source.Faces():
        try:
            if face is None or face.isNull() or face.geomType() != "PLANE":
                continue
            bb = face.BoundingBox()
            if bb.zlen > 1.0e-4:
                vertical_intervals.append((bb.zmin, bb.zmax))
        except Exception:
            continue

    if vertical_intervals:
        section_min = max(v[0] for v in vertical_intervals)
        section_max = min(v[1] for v in vertical_intervals)
    else:
        section_min = source_bb.zmin + 0.35 * source_bb.zlen
        section_max = source_bb.zmin + 0.65 * source_bb.zlen

    if section_max <= section_min + 1.0e-5:
        section_z = 0.5 * (source_bb.zmin + source_bb.zmax)
    else:
        section_z = 0.5 * (section_min + section_max)

    section = cq.Workplane("XY").newObject([source]).section(height=section_z)

    # Reject null/degenerate section wires before requesting their bounding
    # boxes. This avoids the void Bnd_Box failure from the previous iteration.
    wire_data = []
    for wire in section.wires().vals():
        try:
            if wire is None or wire.isNull() or not wire.IsClosed():
                continue
            if wire.Length() <= 1.0e-5:
                continue
            bb = wire.BoundingBox()
            if bb.xlen <= 1.0e-5 or bb.ylen <= 1.0e-5:
                continue
            wire_data.append((bb.xlen * bb.ylen, wire, bb))
        except Exception:
            continue

    if len(wire_data) < 2:
        raise ValueError("Could not recover two valid closed frame footprints")

    wire_data.sort(key=lambda item: item[0], reverse=True)
    _, outer_wire, outer_bb = wire_data[0]

    # Select the largest wire that lies inside the outer footprint as the
    # central opening, avoiding coincident duplicate section wires if present.
    inner_entry = None
    dimensional_tol = max(1.0e-4, 1.0e-6 * max(outer_bb.xlen, outer_bb.ylen))
    for entry in wire_data[1:]:
        bb = entry[2]
        if (bb.xlen < outer_bb.xlen - dimensional_tol and
                bb.ylen < outer_bb.ylen - dimensional_tol):
            inner_entry = entry
            break
    if inner_entry is None:
        raise ValueError("Could not distinguish the central opening footprint")

    _, inner_wire, inner_bb = inner_entry

    outer_w = outer_bb.xlen
    outer_h = outer_bb.ylen
    inner_w = inner_bb.xlen
    inner_h = inner_bb.ylen
    cx = 0.5 * (outer_bb.xmin + outer_bb.xmax)
    cy = 0.5 * (outer_bb.ymin + outer_bb.ymax)
    z0 = source_bb.zmin
    depth = source_bb.zlen

    def recover_plan_radius(wire, fallback):
        values = []
        for edge in wire.Edges():
            try:
                if edge is not None and not edge.isNull() and edge.geomType() == "CIRCLE":
                    radius = float(edge.radius())
                    if radius > 1.0e-5:
                        values.append(radius)
            except Exception:
                continue
        return float(statistics.median(values)) if values else float(fallback)

    # These are plan-view corner radii and must remain distinct from the R2
    # cross-sectional edge treatment requested by the edit.
    outer_r = min(recover_plan_radius(outer_wire, 63.0),
                  0.499 * outer_w, 0.499 * outer_h)
    inner_r = min(recover_plan_radius(inner_wire, 50.0),
                  0.499 * inner_w, 0.499 * inner_h)

    if outer_r <= 0 or inner_r <= 0:
        raise ValueError("Recovered invalid plan-view corner radii")

    # Construct a robust rounded-rectangle prism as the union of two boxes and
    # four corner cylinders. This avoids fragile manually assembled arc wires.
    def rounded_prism(width, height, radius, base_z, prism_depth):
        if width <= 2.0 * radius or height <= 2.0 * radius:
            raise ValueError("Rounded rectangle dimensions are incompatible with its radius")

        shape = (
            cq.Workplane("XY", origin=(cx, cy, base_z))
            .box(width - 2.0 * radius, height, prism_depth,
                 centered=(True, True, False))
            .union(
                cq.Workplane("XY", origin=(cx, cy, base_z))
                .box(width, height - 2.0 * radius, prism_depth,
                     centered=(True, True, False))
            )
        )

        dx = 0.5 * width - radius
        dy = 0.5 * height - radius
        for sx in (-1.0, 1.0):
            for sy in (-1.0, 1.0):
                corner = (
                    cq.Workplane("XY", origin=(cx + sx * dx, cy + sy * dy, base_z))
                    .circle(radius)
                    .extrude(prism_depth)
                )
                shape = shape.union(corner)

        result = shape.clean().val()
        if result is None or result.isNull() or not result.isValid():
            raise ValueError("Failed to construct a valid rounded-rectangle prism")
        return result

    outer_solid = rounded_prism(outer_w, outer_h, outer_r, z0, depth)
    cutter_margin = max(1.0, 0.1 * depth)
    inner_cutter = rounded_prism(
        inner_w,
        inner_h,
        inner_r,
        z0 - cutter_margin,
        depth + 2.0 * cutter_margin,
    )

    sharp_frame = outer_solid.cut(inner_cutter).clean()
    if sharp_frame is None or sharp_frame.isNull() or not sharp_frame.isValid():
        raise ValueError("The reconstructed unfilleted frame is invalid")
    if abs(sharp_frame.Volume()) <= 1.0e-6:
        raise ValueError("The reconstructed frame has no volume")

    # Select every inner and outer boundary edge at both axial ends. Filleting
    # these four continuous edge loops to R2 recreates the three existing R2
    # transitions and replaces the rear-outer R10 transition with R2.
    ztol = max(1.0e-5, depth * 1.0e-6)
    end_edges = []

    for edge in sharp_frame.Edges():
        try:
            if edge is None or edge.isNull():
                continue
            vertices = edge.Vertices()
            if not vertices:
                continue
            z_values = [v.Center().z for v in vertices]
            at_bottom = all(abs(z - z0) <= ztol for z in z_values)
            at_top = all(abs(z - (z0 + depth)) <= ztol for z in z_values)
            if at_bottom or at_top:
                end_edges.append(edge)
        except Exception:
            continue

    if len(end_edges) < 8:
        raise ValueError("Too few axial end edges were identified: %d" % len(end_edges))

    target_radius = 2.0
    if depth <= 2.0 * target_radius:
        raise ValueError("Frame depth is too small for opposed R2 edge fillets")

    result = sharp_frame.fillet(target_radius, end_edges).clean()
    if result is None or result.isNull() or not result.isValid():
        raise ValueError("The uniform-R2 frame result is invalid")
    if abs(result.Volume()) <= 1.0e-6:
        raise ValueError("The uniform-R2 frame result has no volume")

    result_bb = result.BoundingBox()
    print("Source envelope:", source_bb.xlen, source_bb.ylen, source_bb.zlen)
    print("Section Z:", section_z)
    print("Recovered outer footprint:", outer_w, outer_h, "plan R", outer_r)
    print("Recovered inner footprint:", inner_w, inner_h, "plan R", inner_r)
    print("Profile boundary edges filleted:", len(end_edges))
    print("Rear outer profile radius changed from nominal R10 to R2")
    print("All four cross-sectional edge loops are now R2")
    print("Result envelope:", result_bb.xlen, result_bb.ylen, result_bb.zlen)
    print("Result valid:", result.isValid())

    return cq.Workplane("XY").newObject([result])