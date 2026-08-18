def my_cad_function(args):
    import os
    import cadquery as cq

    shape = cq.importers.importStep(os.path.expanduser(args["input_file"]))
    solid = shape.val()
    print("INPUT_VALID", solid.isValid(), "VOLUME", solid.Volume())

    # Locate the two planar aperture sidewalls normal to global X. Their
    # midpoint supplies the in-plane center of the rounded rectangular frame.
    x_side_faces = []
    for face in solid.Faces():
        if face.geomType() != "PLANE":
            continue
        c = face.Center()
        try:
            n0 = face.normalAt(c)
        except Exception:
            continue
        if abs(n0.x) > 0.99 and face.Area() > 5000.0:
            x_side_faces.append(face)

    if len(x_side_faces) < 2:
        raise RuntimeError("Could not identify the opposed planar aperture sidewalls")

    x_side_faces = sorted(x_side_faces, key=lambda f: f.Center().x)
    left_face = x_side_faces[0]
    right_face = x_side_faces[-1]
    lc = left_face.Center()
    rc = right_face.Center()
    frame_center = cq.Vector(
        0.5 * (lc.x + rc.x),
        0.5 * (lc.y + rc.y),
        0.5 * (lc.z + rc.z)
    )
    aperture_half_width = 0.5 * abs(rc.x - lc.x)

    # The rear/bottom datum is the smaller of the two planar annular faces.
    annular_faces = []
    for face in solid.Faces():
        if face.geomType() == "PLANE" and len(face.Wires()) >= 2:
            annular_faces.append(face)
    if not annular_faces:
        raise RuntimeError("Could not identify a planar annular rear seating face")

    rear_face = min(annular_faces, key=lambda f: f.Area())
    rear_center = rear_face.Center()
    rear_normal = rear_face.normalAt(rear_center).normalized()

    # Project the frame center onto the rear seating plane.
    plane_offset = rear_center.dot(rear_normal)
    center_offset = plane_offset - frame_center.dot(rear_normal)
    datum_origin = frame_center + rear_normal.multiply(center_offset)

    # Establish the second in-plane axis from the aperture's horizontal walls.
    # It is perpendicular to global X and to the rear normal.
    x_dir = cq.Vector(1.0, 0.0, 0.0)
    y_dir = rear_normal.cross(x_dir).normalized()

    # Recover the aperture half-height from the two large planar horizontal
    # inner walls by measuring their centers along the local Y direction.
    horizontal_inner_faces = []
    for face in solid.Faces():
        if face.geomType() != "PLANE" or face.Area() < 9000.0:
            continue
        c = face.Center()
        try:
            fn = face.normalAt(c).normalized()
        except Exception:
            continue
        if abs(fn.dot(y_dir)) > 0.95:
            horizontal_inner_faces.append(face)

    if len(horizontal_inner_faces) >= 2:
        local_positions = [(f.Center() - frame_center).dot(y_dir) for f in horizontal_inner_faces]
        aperture_half_height = 0.5 * (max(local_positions) - min(local_positions))
    else:
        aperture_half_height = 280.0

    print("REAR_DATUM_AREA", rear_face.Area())
    print("REAR_NORMAL", rear_normal.x, rear_normal.y, rear_normal.z)
    print("APERTURE_HALF_DIMS", aperture_half_width, aperture_half_height)

    # Original aperture corners are R50. The requested 20 mm inward offset
    # therefore produces a reduced inner loop with R30 corners.
    aperture_radius = 50.0
    offset = 20.0
    support_height = 5.0
    top_fillet_radius = 2.0

    inner_half_width = aperture_half_width - offset
    inner_half_height = aperture_half_height - offset
    inner_radius = aperture_radius - offset
    if min(inner_half_width, inner_half_height, inner_radius) <= 0:
        raise RuntimeError("The requested 20 mm aperture offset self-intersects")

    # Extend the outer support boundary slightly beneath the existing rear land.
    # This creates a finite shared attachment area for a reliable additive fuse,
    # without changing the external envelope.
    attachment_overlap = 0.5
    outer_width = 2.0 * (aperture_half_width + attachment_overlap)
    outer_height = 2.0 * (aperture_half_height + attachment_overlap)
    outer_radius = aperture_radius + attachment_overlap
    inner_width = 2.0 * inner_half_width
    inner_height = 2.0 * inner_half_height

    support_plane = cq.Plane(origin=datum_origin, xDir=x_dir, normal=rear_normal)

    outer_wire = (
        cq.Workplane(support_plane)
        .rect(outer_width, outer_height)
        .vertices()
        .fillet2D(outer_radius)
        .val()
    )
    inner_wire = (
        cq.Workplane(support_plane)
        .rect(inner_width, inner_height)
        .vertices()
        .fillet2D(inner_radius)
        .val()
    )

    outer_face = cq.Face.makeFromWires(outer_wire)
    inner_face = cq.Face.makeFromWires(inner_wire)
    extrusion_vector = rear_normal.multiply(support_height)
    support = outer_face.extrude(extrusion_vector).cut(inner_face.extrude(extrusion_vector))

    # Select the smaller wire on the planar face at the original rear datum.
    # It is the exposed upper inner edge loop. Fillet only this loop; all edges
    # on the generated underside are deliberately left sharp.
    top_candidates = []
    for face in support.Faces():
        if face.geomType() != "PLANE" or len(face.Wires()) < 2:
            continue
        fc = face.Center()
        distance = abs((fc - datum_origin).dot(rear_normal))
        if distance < 1.0e-4:
            top_candidates.append(face)

    if not top_candidates:
        raise RuntimeError("Could not identify the upper annular face of the support")

    support_top = max(top_candidates, key=lambda f: f.Area())
    top_wires = support_top.Wires()
    inner_top_wire = min(top_wires, key=lambda w: sum(e.Length() for e in w.Edges()))
    upper_edges = inner_top_wire.Edges()
    support = support.makeFillet(top_fillet_radius, upper_edges)
    print("TOP_FILLET_EDGE_COUNT", len(upper_edges))

    # Add the support to the original frame. The support terminates exactly
    # 5 mm from the original rear datum, making its underside planar and
    # parallel to that datum.
    result = solid.fuse(support).clean()

    print("RESULT_VALID", result.isValid())
    print("RESULT_SOLIDS", len(result.Solids()))
    print("RESULT_VOLUME", result.Volume())
    print("ADDED_VOLUME", result.Volume() - solid.Volume())
    print("RESULT_FACES", len(result.Faces()), "RESULT_EDGES", len(result.Edges()))

    if not result.isValid() or len(result.Solids()) != 1:
        raise RuntimeError("Supporting step did not fuse into one valid watertight solid")

    return cq.Workplane(obj=result)
