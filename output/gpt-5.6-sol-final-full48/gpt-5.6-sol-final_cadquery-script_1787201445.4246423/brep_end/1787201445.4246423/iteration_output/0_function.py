def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    source = imported.val() if hasattr(imported, "val") else imported
    source_bb = source.BoundingBox()

    # Find a Z level common to the unfilleted vertical inner and outer walls.
    # A section at this level reproduces the original rounded-rectangle footprint
    # without inheriting either the R10 rear rounding or the existing R2 rounds.
    wall_intervals = []
    for face in source.Faces():
        try:
            if face.geomType() != "PLANE":
                continue
            normal = face.normalAt()
            if abs(normal.z) < 0.05:
                bb = face.BoundingBox()
                if bb.zlen > 1.0e-5:
                    wall_intervals.append((bb.zmin, bb.zmax))
        except Exception:
            pass

    if wall_intervals:
        common_min = max(interval[0] for interval in wall_intervals)
        common_max = min(interval[1] for interval in wall_intervals)
        if common_max > common_min + 1.0e-6:
            section_z = 0.5 * (common_min + common_max)
        else:
            section_z = 0.5 * (source_bb.zmin + source_bb.zmax)
    else:
        section_z = 0.5 * (source_bb.zmin + source_bb.zmax)

    section_result = cq.Workplane("XY").newObject([source]).section(height=section_z)
    section_wires = section_result.wires().vals()
    closed_wires = [wire for wire in section_wires if wire.IsClosed()]

    if len(closed_wires) < 2:
        raise ValueError(
            "Could not recover the outer and inner closed rounded-rectangle wires "
            "from the source solid."
        )

    # The outer and inner opening wires are the two largest section loops.
    def projected_box_area(wire):
        bb = wire.BoundingBox()
        return bb.xlen * bb.ylen

    closed_wires.sort(key=projected_box_area, reverse=True)
    outer_wire = closed_wires[0]
    inner_wire = closed_wires[1]

    # Move the recovered footprint to the original lower support plane and
    # reconstruct the sharp annular prism through the original overall depth.
    move_to_bottom = cq.Vector(0, 0, source_bb.zmin - section_z)
    outer_bottom = outer_wire.translate(move_to_bottom)
    inner_bottom = inner_wire.translate(move_to_bottom)
    depth = source_bb.zlen

    sharp_frame = cq.Solid.extrudeLinear(
        outer_bottom,
        [inner_bottom],
        cq.Vector(0, 0, depth)
    )

    # Select every inner and outer edge on both axial ends. Applying one R2
    # operation to this set gives the front-inner, front-outer, rear-inner, and
    # rear-outer transitions the same cross-sectional radius.
    bb = sharp_frame.BoundingBox()
    z_tolerance = max(1.0e-6, depth * 1.0e-7)
    axial_end_edges = []
    for edge in sharp_frame.Edges():
        ebb = edge.BoundingBox()
        if ebb.zlen <= z_tolerance:
            edge_z = edge.Center().z
            if (abs(edge_z - bb.zmin) <= z_tolerance * 10.0 or
                    abs(edge_z - bb.zmax) <= z_tolerance * 10.0):
                axial_end_edges.append(edge)

    if not axial_end_edges:
        raise ValueError("No axial end perimeter edges were found for the R2 fillet.")

    result = sharp_frame.makeFillet(2.0, axial_end_edges)

    if not result.isValid():
        raise ValueError("The reconstructed uniformly filleted frame is invalid.")

    print("Source bounding box:", source_bb.xlen, source_bb.ylen, source_bb.zlen)
    print("Section Z:", section_z)
    print("Recovered closed section wires:", len(closed_wires))
    print("Applied uniform R2 fillets to", len(axial_end_edges), "end edges")
    print("Result valid:", result.isValid(), "solids:", len(result.Solids()))
    return cq.Workplane(obj=result)