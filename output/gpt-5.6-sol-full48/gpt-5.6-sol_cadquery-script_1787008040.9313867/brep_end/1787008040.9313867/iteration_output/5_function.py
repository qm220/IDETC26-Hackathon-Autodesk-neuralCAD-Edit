def my_cad_function(args):
    import os
    import math
    import cadquery as cq

    model = cq.importers.importStep(os.path.expanduser(args["input_file"]))
    source = model.val()
    if not source.isValid():
        raise RuntimeError("Imported source model is invalid")

    source_volume = source.Volume()
    print("INPUT_VALID", source.isValid(), "VOLUME", source_volume)

    # Identify the opposed planar sidewalls of the central aperture.
    x_inner_faces = []
    for face in source.Faces():
        if face.geomType() != "PLANE" or face.Area() < 5000.0:
            continue
        center = face.Center()
        try:
            normal = face.normalAt(center).normalized()
        except Exception:
            continue
        if abs(normal.x) > 0.99:
            x_inner_faces.append(face)

    if len(x_inner_faces) < 2:
        raise RuntimeError("Could not identify both opposed aperture sidewalls")

    x_inner_faces.sort(key=lambda f: f.Center().x)
    left_center = x_inner_faces[0].Center()
    right_center = x_inner_faces[-1].Center()
    aperture_half_width = 0.5 * abs(right_center.x - left_center.x)
    frame_center = cq.Vector(
        0.5 * (left_center.x + right_center.x),
        0.5 * (left_center.y + right_center.y),
        0.5 * (left_center.z + right_center.z)
    )

    # Select the smaller planar annular face as the rear/bottom datum.
    annular_faces = [
        face for face in source.Faces()
        if face.geomType() == "PLANE" and len(face.Wires()) >= 2
    ]
    if not annular_faces:
        raise RuntimeError("Could not identify a planar rear annular datum")

    print("ANNULAR_FACE_CANDIDATES", [round(f.Area(), 3) for f in annular_faces])
    rear_face = min(annular_faces, key=lambda f: f.Area())
    rear_center = rear_face.Center()
    rear_normal = rear_face.normalAt(rear_center).normalized()

    plane_constant = rear_center.dot(rear_normal)
    datum_origin = frame_center + rear_normal.multiply(
        plane_constant - frame_center.dot(rear_normal)
    )

    x_direction = cq.Vector(1.0, 0.0, 0.0)
    y_direction = rear_normal.cross(x_direction).normalized()

    # Recover the other aperture dimension from the long opposed sidewalls.
    y_inner_faces = []
    for face in source.Faces():
        if face.geomType() != "PLANE" or face.Area() < 9000.0:
            continue
        center = face.Center()
        try:
            normal = face.normalAt(center).normalized()
        except Exception:
            continue
        if abs(normal.dot(y_direction)) > 0.95:
            y_inner_faces.append(face)

    if len(y_inner_faces) >= 2:
        y_positions = [
            (face.Center() - frame_center).dot(y_direction)
            for face in y_inner_faces
        ]
        aperture_half_height = 0.5 * (max(y_positions) - min(y_positions))
    else:
        aperture_half_height = 280.0
        print("WARNING_USING_FALLBACK_APERTURE_HALF_HEIGHT", aperture_half_height)

    print("REAR_DATUM_AREA", rear_face.Area())
    print("REAR_NORMAL", rear_normal.x, rear_normal.y, rear_normal.z)
    print("APERTURE_HALF_DIMS", aperture_half_width, aperture_half_height)

    aperture_radius = 50.0
    inward_offset = 20.0
    support_height = 5.0
    upper_fillet_radius = 2.0

    support_inner_half_width = aperture_half_width - inward_offset
    support_inner_half_height = aperture_half_height - inward_offset
    support_inner_radius = aperture_radius - inward_offset

    if support_inner_radius <= 0.0:
        raise RuntimeError("The requested offset produces a nonpositive corner radius")
    if support_inner_half_width <= support_inner_radius:
        raise RuntimeError("The requested offset self-intersects across the aperture width")
    if support_inner_half_height <= support_inner_radius:
        raise RuntimeError("The requested offset self-intersects across the aperture height")

    sketch_plane = cq.Plane(
        origin=datum_origin,
        xDir=x_direction,
        normal=rear_normal
    )

    def rounded_rectangle_wire(half_width, half_height, radius, axial_offset=0.0):
        if radius <= 0.0 or radius >= min(half_width, half_height):
            raise ValueError("Invalid rounded-rectangle dimensions")

        d = radius / math.sqrt(2.0)
        local_points = [
            (-half_width + radius, -half_height),
            ( half_width - radius, -half_height),
            ( half_width - radius + d, -half_height + radius - d),
            ( half_width, -half_height + radius),
            ( half_width,  half_height - radius),
            ( half_width - radius + d, half_height - radius + d),
            ( half_width - radius, half_height),
            (-half_width + radius, half_height),
            (-half_width + radius - d, half_height - radius + d),
            (-half_width, half_height - radius),
            (-half_width, -half_height + radius),
            (-half_width + radius - d, -half_height + radius - d),
            (-half_width + radius, -half_height)
        ]
        shift = rear_normal.multiply(axial_offset)
        points = [
            sketch_plane.toWorldCoords(cq.Vector(x, y, 0.0)) + shift
            for x, y in local_points
        ]
        edges = [
            cq.Edge.makeLine(points[0], points[1]),
            cq.Edge.makeThreePointArc(points[1], points[2], points[3]),
            cq.Edge.makeLine(points[3], points[4]),
            cq.Edge.makeThreePointArc(points[4], points[5], points[6]),
            cq.Edge.makeLine(points[6], points[7]),
            cq.Edge.makeThreePointArc(points[7], points[8], points[9]),
            cq.Edge.makeLine(points[9], points[10]),
            cq.Edge.makeThreePointArc(points[10], points[11], points[12])
        ]
        return cq.Wire.assembleEdges(edges)

    # Main 5 mm support. Its outer boundary extends only 2 mm into the existing
    # frame footprint, while its inner boundary is offset 20 mm into the opening.
    main_outer_allowance = 2.0
    main_outer_wire = rounded_rectangle_wire(
        aperture_half_width + main_outer_allowance,
        aperture_half_height + main_outer_allowance,
        aperture_radius + main_outer_allowance
    )
    main_inner_wire = rounded_rectangle_wire(
        support_inner_half_width,
        support_inner_half_height,
        support_inner_radius
    )

    support = cq.Solid.extrudeLinear(
        main_outer_wire,
        [main_inner_wire],
        rear_normal.multiply(support_height)
    )
    if not support.isValid():
        raise RuntimeError("The unfilleted support extrusion is invalid")

    # Apply R2 only to the inner edge of the support's upper cap. The two edge
    # loops on the terminal underside are not selected and therefore stay sharp.
    upper_caps = []
    for face in support.Faces():
        if face.geomType() != "PLANE" or len(face.Wires()) < 2:
            continue
        distance = (face.Center() - datum_origin).dot(rear_normal)
        if abs(distance) < 1.0e-4:
            upper_caps.append(face)

    if not upper_caps:
        raise RuntimeError("Could not identify the support upper cap")

    upper_cap = max(upper_caps, key=lambda f: f.Area())
    upper_inner_wire = min(
        upper_cap.Wires(),
        key=lambda w: sum(e.Length() for e in w.Edges())
    )
    upper_edges = upper_inner_wire.Edges()
    print("TOP_FILLET_EDGE_COUNT", len(upper_edges))

    support = cq.Workplane(obj=support).newObject(upper_edges).fillet(
        upper_fillet_radius
    ).val()
    if not support.isValid():
        raise RuntimeError("The support became invalid after the upper R2 fillet")

    # A narrow hidden bonding collar crosses the rear datum. This creates true
    # volumetric overlap with both the source and the main support, avoiding the
    # unreliable face-only contact that left two solids in the previous result.
    collar_inner_allowance = 0.75
    collar_outer_allowance = 1.75
    collar_back_depth = 3.0
    collar_forward_depth = 1.0

    collar_outer_wire = rounded_rectangle_wire(
        aperture_half_width + collar_outer_allowance,
        aperture_half_height + collar_outer_allowance,
        aperture_radius + collar_outer_allowance,
        axial_offset=-collar_back_depth
    )
    collar_inner_wire = rounded_rectangle_wire(
        aperture_half_width + collar_inner_allowance,
        aperture_half_height + collar_inner_allowance,
        aperture_radius + collar_inner_allowance,
        axial_offset=-collar_back_depth
    )
    collar = cq.Solid.extrudeLinear(
        collar_outer_wire,
        [collar_inner_wire],
        rear_normal.multiply(collar_back_depth + collar_forward_depth)
    )
    if not collar.isValid():
        raise RuntimeError("The hidden bonding collar is invalid")

    source_with_collar = source.fuse(collar).clean()
    print("SOURCE_COLLAR_SOLIDS", len(source_with_collar.Solids()))
    if len(source_with_collar.Solids()) != 1:
        raise RuntimeError("Bonding collar does not intersect the original frame")

    result = source_with_collar.fuse(support).clean()

    print("RESULT_VALID", result.isValid())
    print("RESULT_SOLIDS", len(result.Solids()))
    print("RESULT_VOLUME", result.Volume())
    print("ADDED_VOLUME", result.Volume() - source_volume)
    print("RESULT_FACES", len(result.Faces()), "RESULT_EDGES", len(result.Edges()))

    if not result.isValid():
        raise RuntimeError("The modified frame is not a valid solid")
    if len(result.Solids()) != 1:
        raise RuntimeError("The supporting step still did not fuse into one solid")
    if result.Volume() <= source_volume:
        raise RuntimeError("No supporting material was added")

    # Check for a planar terminal face exactly 5 mm from the rear datum.
    bottom_faces = []
    for face in result.Faces():
        if face.geomType() != "PLANE":
            continue
        distance = (face.Center() - datum_origin).dot(rear_normal)
        if abs(distance - support_height) < 1.0e-3:
            bottom_faces.append(face)
    print("FLAT_BOTTOM_FACE_COUNT", len(bottom_faces))
    if not bottom_faces:
        raise RuntimeError("No flat support underside was found at the required 5 mm depth")

    return cq.Workplane(obj=result)
