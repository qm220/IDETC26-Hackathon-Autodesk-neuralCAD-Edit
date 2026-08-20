def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file).val()
    solids = list(imported.Solids())

    if len(solids) != 3:
        raise ValueError("Expected 3 solids, found %d" % len(solids))

    # Ground R01 by its analyzed STEP bounding-box dimensions.
    target_index = min(
        range(len(solids)),
        key=lambda i: (
            abs(solids[i].BoundingBox().xlen - 331.753222)
            + abs(solids[i].BoundingBox().ylen - 12.700000)
            + abs(solids[i].BoundingBox().zlen - 231.430908)
        )
    )
    target_solid = solids[target_index]
    bb = target_solid.BoundingBox()

    print("=== R01 longitudinal-edge grounding ===")
    print("Selected solid:", target_index)
    print("R01 bbox: %.6f %.6f %.6f" % (bb.xlen, bb.ylen, bb.zlen))

    # Inspection of the imported topology identifies the continuous sharp
    # longitudinal boundary associated with FACE 21. It is the unique 381 mm
    # straight edge at y=0 and is opposite the existing cylindrical wall.
    grounded = []
    for edge_index, edge in enumerate(target_solid.Edges()):
        try:
            edge_type = edge.geomType()
        except Exception:
            edge_type = "UNKNOWN"

        length = edge.Length()
        center = edge.Center()
        if edge_type == "LINE" and abs(length - 381.0) < 0.05 and abs(center.y) < 0.01:
            p0 = edge.startPoint()
            p1 = edge.endPoint()
            grounded.append((edge_index, edge, p0, p1))
            print(
                "Candidate %d: L=%.6f C=(%.6f,%.6f,%.6f) "
                "P0=(%.6f,%.6f,%.6f) P1=(%.6f,%.6f,%.6f)"
                % (edge_index, length, center.x, center.y, center.z,
                   p0.x, p0.y, p0.z, p1.x, p1.y, p1.z)
            )

    if len(grounded) != 1:
        raise ValueError(
            "Expected one grounded 381 mm sharp longitudinal edge; found %d"
            % len(grounded)
        )

    edge_index, target_edge, p0, p1 = grounded[0]

    # Establish a local orthonormal frame at the target edge. The first
    # material-interior direction is +Y because the edge is at y=0 and R01
    # occupies y=0..12.7. Derive the other material-interior direction from
    # the solid center so the construction remains tied to loaded geometry.
    edge_vector = p1.sub(p0)
    edge_length = edge_vector.Length
    axis = edge_vector.normalized()
    inward_y = cq.Vector(0.0, 1.0, 0.0)
    edge_center = target_edge.Center()
    solid_center = target_solid.Center()
    toward_center = solid_center.sub(edge_center)

    projected = toward_center.sub(axis.multiply(toward_center.dot(axis)))
    projected = projected.sub(inward_y.multiply(projected.dot(inward_y)))
    if projected.Length < 1.0e-6:
        raise ValueError("Could not derive the second material-interior direction")
    inward_side = projected.normalized()

    print("Grounded target edge index:", edge_index)
    print("Edge axis: (%.9f, %.9f, %.9f)" % (axis.x, axis.y, axis.z))
    print("Interior +Y direction: (%.9f, %.9f, %.9f)" %
          (inward_y.x, inward_y.y, inward_y.z))
    print("Interior side direction: (%.9f, %.9f, %.9f)" %
          (inward_side.x, inward_side.y, inward_side.z))

    # A native OCC fillet at exactly 6.35 mm fails because this is a limiting
    # half-thickness radius. Construct the mathematically equivalent fillet by
    # removing the corner region bounded by the two original planar faces and
    # an exact R6.35 quarter-circle. This affects only the grounded continuous
    # longitudinal boundary and does not select any end, bore, hole, pivot, or
    # transition edge.
    radius = 6.350000
    extension = 0.05
    start = p0.sub(axis.multiply(extension))
    sweep_length = edge_length + 2.0 * extension

    # CadQuery Plane yDir equals normal cross xDir. With normal=axis and
    # xDir=+Y, determine whether positive or negative plane-y represents the
    # derived inward-side direction.
    plane = cq.Plane(
        origin=(start.x, start.y, start.z),
        xDir=(inward_y.x, inward_y.y, inward_y.z),
        normal=(axis.x, axis.y, axis.z)
    )
    plane_y = cq.Vector(plane.yDir.x, plane.yDir.y, plane.yDir.z)
    side_sign = 1.0 if plane_y.dot(inward_side) >= 0.0 else -1.0

    # Removed cross-section: corner -> first tangent -> exact circular arc ->
    # second tangent -> corner. The arc center is at (R,R) in material-local
    # coordinates and therefore creates an exact convex edge radius R6.35.
    tangent_1 = (radius, 0.0)
    q = radius - radius / (2.0 ** 0.5)
    arc_mid = (q, side_sign * q)
    tangent_2 = (0.0, side_sign * radius)

    cutter_wp = (
        cq.Workplane(plane)
        .moveTo(0.0, 0.0)
        .lineTo(tangent_1[0], tangent_1[1])
        .threePointArc(arc_mid, tangent_2)
        .close()
        .extrude(sweep_length)
    )
    cutter = cutter_wp.val()

    print("Constructed exact R%.6f swept corner-removal tool" % radius)
    print("Sweep length: %.6f" % sweep_length)
    print("Original R01 volume: %.6f" % target_solid.Volume())

    edited_solid = target_solid.cut(cutter)
    if edited_solid.ShapeType() != "Solid":
        edited_parts = list(edited_solid.Solids())
        if len(edited_parts) != 1:
            raise ValueError("Corner-radius cut did not produce exactly one R01 solid")
        edited_solid = edited_parts[0]

    if not edited_solid.isValid():
        raise ValueError("Edited R01 is invalid")

    removed_volume = target_solid.Volume() - edited_solid.Volume()
    expected_area = radius * radius - 3.141592653589793 * radius * radius / 4.0
    expected_volume = expected_area * edge_length

    print("Edited R01 volume:   %.6f" % edited_solid.Volume())
    print("Removed volume:      %.6f" % removed_volume)
    print("Expected nominal removed volume: %.6f" % expected_volume)
    print("Original R01 faces: %d" % len(target_solid.Faces()))
    print("Edited R01 faces:   %d" % len(edited_solid.Faces()))

    if removed_volume <= 0.0:
        raise ValueError("Radius construction removed no material")
    if abs(removed_volume - expected_volume) > max(2.0, expected_volume * 0.02):
        raise ValueError(
            "Removed volume does not match an R6.35 longitudinal corner radius"
        )

    # Replace only R01 and preserve the two other original solids unchanged.
    output_solids = list(solids)
    output_solids[target_index] = edited_solid
    result = cq.Compound.makeCompound(output_solids)

    if len(result.Solids()) != 3:
        raise ValueError("Result no longer contains the original three solids")
    if not result.isValid():
        raise ValueError("Resulting three-solid compound is invalid")

    print("Exact requested radius: 6.350000 mm (0.635 cm)")
    print("Result solids:", len(result.Solids()))
    print("Result valid:", result.isValid())
    return cq.Workplane(obj=result)
