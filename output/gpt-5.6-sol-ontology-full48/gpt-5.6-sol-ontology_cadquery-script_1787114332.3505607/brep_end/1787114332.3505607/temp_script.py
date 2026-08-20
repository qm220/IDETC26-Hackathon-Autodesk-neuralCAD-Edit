def my_cad_function(args):
    import os
    import math

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    model = imported.val() if hasattr(imported, "val") else imported

    print("Loaded STEP:", input_file)
    print("Model valid:", model.isValid())
    faces = list(model.Faces())
    print("Global face count:", len(faces))

    # Bind the planning-stage face references to the imported STEP topology.
    for idx in [513, 593, 670, 671, 672, 673, 779]:
        if idx >= len(faces):
            continue
        face = faces[idx]
        c = face.Center()
        bb = face.BoundingBox()
        try:
            geom_type = face.geomType()
        except Exception:
            geom_type = "UNKNOWN"
        print(
            "FACE %d: type=%s area=%.6f center=(%.6f, %.6f, %.6f) "
            "bbox=(%.6f, %.6f, %.6f)-(%.6f, %.6f, %.6f)"
            % (
                idx, geom_type, face.Area(), c.x, c.y, c.z,
                bb.xmin, bb.ymin, bb.zmin,
                bb.xmax, bb.ymax, bb.zmax,
            )
        )

    solids = list(model.Solids())
    if len(solids) < 2:
        raise ValueError("Expected a sprocket solid and a separate spline insert")

    def radial_extent(shape):
        radii = [math.hypot(v.Center().x, v.Center().z) for v in shape.Vertices()]
        if radii:
            return max(radii)
        bb = shape.BoundingBox()
        return max(
            math.hypot(x, z)
            for x in (bb.xmin, bb.xmax)
            for z in (bb.zmin, bb.zmax)
        )

    # Identify SOLID 1 geometrically as the component with the largest radius.
    solid_data = sorted(
        [(radial_extent(s), s) for s in solids],
        key=lambda item: item[0],
        reverse=True,
    )
    sprocket = solid_data[0][1]
    preserved_solids = [item[1] for item in solid_data[1:]]

    for i, (radius, solid) in enumerate(solid_data):
        bb = solid.BoundingBox()
        print(
            "Sorted solid %d: volume=%.6f radial_extent=%.6f "
            "bbox=(%.6f, %.6f, %.6f)-(%.6f, %.6f, %.6f)"
            % (
                i, solid.Volume(), radius,
                bb.xmin, bb.ymin, bb.zmin,
                bb.xmax, bb.ymax, bb.zmax,
            )
        )

    outside_radius = radial_extent(sprocket)
    tooth_count = 27
    pressure_angle = math.radians(20.0)

    # Fit a standard full-depth 27-tooth involute spur profile to the existing
    # radial envelope because the request supplies no new pitch or module.
    module = 2.0 * outside_radius / float(tooth_count + 2)
    pitch_radius = module * tooth_count / 2.0
    base_radius = pitch_radius * math.cos(pressure_angle)
    root_radius = pitch_radius - 1.25 * module
    addendum_radius = outside_radius

    if not (0.0 < root_radius < base_radius < addendum_radius):
        raise ValueError("Unable to derive a valid involute gear envelope")

    # Derive the actual axial tooth span from vertices in the outer radial zone,
    # rather than using the thicker hub's global bounding box.
    outer_vertices = []
    outer_threshold = pitch_radius - 0.20 * module
    for vertex in sprocket.Vertices():
        p = vertex.Center()
        if math.hypot(p.x, p.z) >= outer_threshold:
            outer_vertices.append(p)

    sprocket_bb = sprocket.BoundingBox()
    if outer_vertices:
        tooth_y_min = min(p.y for p in outer_vertices)
        tooth_y_max = max(p.y for p in outer_vertices)
    else:
        tooth_y_min = sprocket_bb.ymin
        tooth_y_max = sprocket_bb.ymax

    if tooth_y_max - tooth_y_min < 0.25 * module:
        tooth_y_min = sprocket_bb.ymin
        tooth_y_max = sprocket_bb.ymax

    tooth_width = tooth_y_max - tooth_y_min
    print(
        "Derived spur gear: teeth=%d module=%.6f root_r=%.6f base_r=%.6f "
        "pitch_r=%.6f outside_r=%.6f tooth_y=[%.6f, %.6f] width=%.6f"
        % (
            tooth_count, module, root_radius, base_radius,
            pitch_radius, addendum_radius,
            tooth_y_min, tooth_y_max, tooth_width,
        )
    )

    # FACE 671 is the cylindrical rounded tip of a representative original
    # tooth. Its centroid grounds the angular phase of the replacement pattern.
    phase = 0.0
    if 671 < len(faces):
        p = faces[671].Center()
        if math.hypot(p.x, p.z) > 0.70 * outside_radius:
            phase = math.atan2(p.z, p.x)
    print("Replacement tooth phase (degrees):", math.degrees(phase))

    # Remove F009 outside the root envelope while preserving the hub, spokes,
    # web openings, and the annular rim inside that envelope.
    radial_overlap = min(0.60, 0.15 * module)
    trim_radius = root_radius + radial_overlap
    axial_pad = max(1.0, 0.20 * (sprocket_bb.ymax - sprocket_bb.ymin))
    trim_cylinder = cq.Solid.makeCylinder(
        trim_radius,
        (sprocket_bb.ymax - sprocket_bb.ymin) + 2.0 * axial_pad,
        cq.Vector(0.0, sprocket_bb.ymin - axial_pad, 0.0),
        cq.Vector(0.0, 1.0, 0.0),
    )
    retained_body = sprocket.intersect(trim_cylinder)
    if retained_body.isNull() or not retained_body.isValid():
        raise ValueError("Failed to produce a valid retained sprocket body")

    def involute(alpha):
        return math.tan(alpha) - alpha

    inv_pressure = involute(pressure_angle)
    half_pitch_tooth_angle = math.pi / (2.0 * tooth_count)
    base_half_angle = half_pitch_tooth_angle + inv_pressure

    def half_angle_at_radius(radius):
        if radius <= base_radius:
            return base_half_angle
        ratio = max(-1.0, min(1.0, base_radius / radius))
        alpha = math.acos(ratio)
        return half_pitch_tooth_angle + inv_pressure - involute(alpha)

    # Build one continuous outer wire for all 27 teeth. This avoids the invalid
    # multi-solid compound fusion produced by the previous implementation.
    profile_points = []
    pitch_angle = 2.0 * math.pi / tooth_count
    flank_samples = 10

    for tooth_index in range(tooth_count):
        center_angle = phase + tooth_index * pitch_angle

        # Root point and radial transition into the negative involute flank.
        a_root_neg = center_angle - base_half_angle
        profile_points.append((
            root_radius * math.cos(a_root_neg),
            root_radius * math.sin(a_root_neg),
        ))
        profile_points.append((
            base_radius * math.cos(a_root_neg),
            base_radius * math.sin(a_root_neg),
        ))

        # Negative flank from base circle to outside circle.
        for j in range(1, flank_samples + 1):
            f = float(j) / float(flank_samples)
            radius = base_radius + f * (addendum_radius - base_radius)
            angle = center_angle - half_angle_at_radius(radius)
            profile_points.append((radius * math.cos(angle), radius * math.sin(angle)))

        # Flat top land. Its extrusion is straight and parallel to the Y axis,
        # giving untwisted spur teeth instead of rounded peripheral lobes.
        tip_half_angle = half_angle_at_radius(addendum_radius)
        profile_points.append((
            addendum_radius * math.cos(center_angle + tip_half_angle),
            addendum_radius * math.sin(center_angle + tip_half_angle),
        ))

        # Positive flank back toward the base circle.
        for j in range(flank_samples - 1, -1, -1):
            f = float(j) / float(flank_samples)
            radius = base_radius + f * (addendum_radius - base_radius)
            angle = center_angle + half_angle_at_radius(radius)
            profile_points.append((radius * math.cos(angle), radius * math.sin(angle)))

        a_root_pos = center_angle + base_half_angle
        profile_points.append((
            root_radius * math.cos(a_root_pos),
            root_radius * math.sin(a_root_pos),
        ))

    polygon_vertices = [
        cq.Vector(x, tooth_y_min, z) for x, z in profile_points
    ]
    polygon_vertices.append(polygon_vertices[0])
    outer_wire = cq.Wire.makePolygon(polygon_vertices)
    outer_face = cq.Face.makeFromWires(outer_wire)
    outer_prism = cq.Solid.extrudeLinear(
        outer_face,
        cq.Vector(0.0, tooth_width, 0.0),
    )

    # Turn the toothed prism into a ring. The ring extends inward past the trim
    # radius so the subsequent boolean has a substantial, non-coincident overlap.
    ring_inner_radius = root_radius - max(0.80, 0.25 * module)
    cut_pad = max(0.5, 0.10 * tooth_width)
    inner_cylinder = cq.Solid.makeCylinder(
        ring_inner_radius,
        tooth_width + 2.0 * cut_pad,
        cq.Vector(0.0, tooth_y_min - cut_pad, 0.0),
        cq.Vector(0.0, 1.0, 0.0),
    )
    gear_ring = outer_prism.cut(inner_cylinder)
    if gear_ring.isNull() or not gear_ring.isValid():
        raise ValueError("The continuous replacement spur-gear ring is invalid")

    rebuilt_sprocket = retained_body.fuse(gear_ring)
    try:
        rebuilt_sprocket = rebuilt_sprocket.clean()
    except Exception as exc:
        print("Non-fatal clean warning:", exc)

    print("Retained body valid:", retained_body.isValid())
    print("Gear ring valid:", gear_ring.isValid())
    print("Rebuilt sprocket valid:", rebuilt_sprocket.isValid())
    print("Rebuilt sprocket solid count:", len(rebuilt_sprocket.Solids()))
    print("Rebuilt sprocket volume:", rebuilt_sprocket.Volume())

    if rebuilt_sprocket.isNull() or not rebuilt_sprocket.isValid():
        raise ValueError("The rebuilt spur gear is not a valid B-rep")
    if len(rebuilt_sprocket.Solids()) != 1:
        raise ValueError("Replacement teeth did not become one solid with the gear")

    # Restore the separate internally splined insert without modifying it.
    result = cq.Compound.makeCompound(
        [rebuilt_sprocket] + preserved_solids
    )
    print("Final compound solid count:", len(result.Solids()))
    print("Final model valid:", result.isValid())

    if not result.isValid():
        raise ValueError("Final two-component model is invalid")
    return result
