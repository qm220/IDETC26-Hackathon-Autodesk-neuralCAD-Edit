def my_cad_function(args):
    import os
    import math
    import statistics
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)

    solids = imported.solids().vals()
    if not solids:
        raise ValueError("The input STEP file contains no solid")

    source = max(solids, key=lambda solid: abs(solid.Volume()))
    source_bb = source.BoundingBox()

    # Recover the unchanged inner and outer rounded-rectangle footprints from
    # a section through the vertical wall region, away from the end fillets.
    wall_intervals = []
    for face in source.Faces():
        try:
            bb = face.BoundingBox()
            if face.geomType() == "PLANE" and bb.zlen > 1.0e-4:
                wall_intervals.append((bb.zmin, bb.zmax))
        except Exception:
            pass

    if wall_intervals:
        section_min = max(interval[0] for interval in wall_intervals)
        section_max = min(interval[1] for interval in wall_intervals)
    else:
        section_min = source_bb.zmin
        section_max = source_bb.zmax

    if section_max > section_min + 1.0e-4:
        section_z = 0.5 * (section_min + section_max)
    else:
        section_z = 0.5 * (source_bb.zmin + source_bb.zmax)

    section = cq.Workplane("XY").newObject([source]).section(height=section_z)
    section_wires = []
    for wire in section.wires().vals():
        try:
            if wire.IsClosed():
                section_wires.append(wire)
        except Exception:
            pass

    if len(section_wires) < 2:
        raise ValueError("Could not recover the inner and outer frame footprints")

    section_wires.sort(
        key=lambda wire: wire.BoundingBox().xlen * wire.BoundingBox().ylen,
        reverse=True,
    )
    outer_wire = section_wires[0]
    inner_wire = section_wires[1]
    outer_bb = outer_wire.BoundingBox()
    inner_bb = inner_wire.BoundingBox()

    outer_w = outer_bb.xlen
    outer_h = outer_bb.ylen
    inner_w = inner_bb.xlen
    inner_h = inner_bb.ylen
    cx = 0.5 * (outer_bb.xmin + outer_bb.xmax)
    cy = 0.5 * (outer_bb.ymin + outer_bb.ymax)
    z0 = source_bb.zmin
    depth = source_bb.zlen

    def recover_plan_radius(wire, fallback):
        radii = []
        for edge in wire.Edges():
            try:
                if not edge.isNull() and edge.geomType() == "CIRCLE":
                    radius = float(edge.radius())
                    if radius > 1.0e-4:
                        radii.append(radius)
            except Exception:
                pass
        if radii:
            return float(statistics.median(radii))
        return float(fallback)

    # Preserve the plan-view path radii. These are distinct from the profile
    # edge radii requested by the edit.
    outer_r = min(
        recover_plan_radius(outer_wire, 63.0),
        0.499 * outer_w,
        0.499 * outer_h,
    )
    inner_r = min(
        recover_plan_radius(inner_wire, 50.0),
        0.499 * inner_w,
        0.499 * inner_h,
    )

    def rounded_rectangle(width, height, radius, z):
        hw = 0.5 * width
        hh = 0.5 * height
        d = radius / math.sqrt(2.0)
        return (
            cq.Workplane("XY", origin=(cx, cy, z))
            .moveTo(-hw + radius, -hh)
            .lineTo(hw - radius, -hh)
            .threePointArc(
                (hw - radius + d, -hh + radius - d),
                (hw, -hh + radius),
            )
            .lineTo(hw, hh - radius)
            .threePointArc(
                (hw - radius + d, hh - radius + d),
                (hw - radius, hh),
            )
            .lineTo(-hw + radius, hh)
            .threePointArc(
                (-hw + radius - d, hh - radius + d),
                (-hw, hh - radius),
            )
            .lineTo(-hw, -hh + radius)
            .threePointArc(
                (-hw + radius - d, -hh + radius - d),
                (-hw + radius, -hh),
            )
            .close()
        )

    outer_solid = rounded_rectangle(outer_w, outer_h, outer_r, z0).extrude(depth).val()
    cutter_margin = max(1.0, 0.1 * depth)
    inner_cutter = (
        rounded_rectangle(inner_w, inner_h, inner_r, z0 - cutter_margin)
        .extrude(depth + 2.0 * cutter_margin)
        .val()
    )

    sharp_frame = outer_solid.cut(inner_cutter).clean()
    if sharp_frame.isNull() or not sharp_frame.isValid():
        raise ValueError("The reconstructed unfilleted frame is invalid")

    # Identify the profile edges from the horizontal annular end faces. This
    # avoids relying on edge bounding boxes or on source-model Z coordinates.
    rebuilt_bb = sharp_frame.BoundingBox()
    ztol = max(1.0e-5, depth * 1.0e-6)
    top_faces = []
    bottom_faces = []

    for face in sharp_frame.Faces():
        try:
            if face.geomType() != "PLANE":
                continue
            bb = face.BoundingBox()
            if bb.zlen > ztol:
                continue
            zc = face.Center().z
            if abs(zc - rebuilt_bb.zmax) <= ztol:
                top_faces.append(face)
            elif abs(zc - rebuilt_bb.zmin) <= ztol:
                bottom_faces.append(face)
        except Exception:
            pass

    if not top_faces or not bottom_faces:
        raise ValueError(
            "Could not identify both annular end faces: top=%d bottom=%d"
            % (len(top_faces), len(bottom_faces))
        )

    end_edges = []

    def append_unique(edge):
        try:
            if edge is None or edge.isNull():
                return
        except Exception:
            return
        for existing in end_edges:
            try:
                if edge.isSame(existing):
                    return
            except Exception:
                pass
        end_edges.append(edge)

    for face in top_faces + bottom_faces:
        for edge in face.Edges():
            append_unique(edge)

    if not end_edges:
        raise ValueError("No profile boundary edges were recovered from the end faces")

    # The other three continuous cross-sectional edge rounds are nominal R2.
    # Applying R2 to all end-face boundaries replaces the rear outer R10 while
    # preserving/recreating the three existing R2 transitions uniformly.
    target_radius = 2.0
    result = sharp_frame.fillet(target_radius, end_edges).clean()

    if result.isNull() or not result.isValid():
        raise ValueError("The uniform R2 frame result is invalid")

    result_bb = result.BoundingBox()
    print("Source envelope:", source_bb.xlen, source_bb.ylen, source_bb.zlen)
    print("Recovered outer footprint:", outer_w, outer_h, "R", outer_r)
    print("Recovered inner footprint:", inner_w, inner_h, "R", inner_r)
    print("Horizontal end faces: top=%d bottom=%d" % (len(top_faces), len(bottom_faces)))
    print("Profile boundary edges filleted:", len(end_edges))
    print("All cross-sectional edge radii set to R2")
    print("Result envelope:", result_bb.xlen, result_bb.ylen, result_bb.zlen)
    print("Result valid:", result.isValid())

    return cq.Workplane("XY").newObject([result])