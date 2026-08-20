def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    source = imported.val() if hasattr(imported, "val") else imported
    source_bb = source.BoundingBox()

    # Recover the unchanged rounded-rectangular footprint from a Z section
    # through the straight portions of both the inner and outer walls.
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
    else:
        common_min = source_bb.zmin
        common_max = source_bb.zmax

    if common_max > common_min + 1.0e-6:
        section_z = 0.5 * (common_min + common_max)
    else:
        # The original model has R2 end rounds and an R10 rear-outer round.
        # This fallback remains away from both axial ends.
        section_z = source_bb.zmin + 0.5 * source_bb.zlen

    section_result = cq.Workplane("XY").newObject([source]).section(height=section_z)
    closed_wires = [wire for wire in section_result.wires().vals() if wire.IsClosed()]

    if len(closed_wires) < 2:
        raise ValueError("Could not recover the inner and outer footprint loops.")

    def projected_box_area(wire):
        bb = wire.BoundingBox()
        return bb.xlen * bb.ylen

    closed_wires.sort(key=projected_box_area, reverse=True)
    outer_wire = closed_wires[0]
    inner_wire = closed_wires[1]

    # Reconstruct the same nominal frame envelope and section depth without any
    # end rounding. This removes the original R10 rear-outer perimeter radius.
    to_bottom = cq.Vector(0, 0, source_bb.zmin - section_z)
    outer_bottom = outer_wire.translate(to_bottom)
    inner_bottom = inner_wire.translate(to_bottom)
    depth = source_bb.zlen

    sharp_frame = cq.Solid.extrudeLinear(
        outer_bottom,
        [inner_bottom],
        cq.Vector(0, 0, depth)
    )

    # Select the inner and outer perimeter edges at both axial ends. Filleting
    # this complete set with R2 makes all four cross-sectional corner radii
    # equal while preserving the rounded-rectangle path and nominal section.
    frame_bb = sharp_frame.BoundingBox()
    z_tol = max(1.0e-6, depth * 1.0e-6)
    axial_end_edges = []
    for edge in sharp_frame.Edges():
        ebb = edge.BoundingBox()
        if ebb.zlen <= z_tol:
            edge_z = edge.Center().z
            if (abs(edge_z - frame_bb.zmin) <= 10.0 * z_tol or
                    abs(edge_z - frame_bb.zmax) <= 10.0 * z_tol):
                axial_end_edges.append(edge)

    if not axial_end_edges:
        raise ValueError("No axial perimeter edges were found for the R2 fillets.")

    # CadQuery exposes solid filleting through Workplane.fillet rather than as
    # a Solid.makeFillet method. newObject retains the parent solid context.
    result_wp = cq.Workplane(obj=sharp_frame).newObject(axial_end_edges).fillet(2.0)
    result = result_wp.val()

    if result is None or not result.isValid():
        raise ValueError("The uniformly R2-filleted frame is invalid.")

    print("Source size:", source_bb.xlen, source_bb.ylen, source_bb.zlen)
    print("Recovered section Z:", section_z)
    print("Closed footprint loops:", len(closed_wires))
    print("R2 axial perimeter edges:", len(axial_end_edges))
    print("Result valid:", result.isValid())
    return result_wp