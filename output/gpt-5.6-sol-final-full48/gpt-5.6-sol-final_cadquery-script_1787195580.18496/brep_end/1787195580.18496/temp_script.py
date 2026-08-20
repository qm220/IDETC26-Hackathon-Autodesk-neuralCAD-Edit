def my_cad_function(args):
    import os
    import math

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    source_shape = imported.val() if hasattr(imported, "val") else imported
    solids = list(source_shape.Solids())
    if not solids:
        raise ValueError("The input STEP file contains no solids")

    # Select the thin sprocket body by its two largest bounding-box dimensions.
    # This avoids assuming that the rotation axis is the global Z axis.
    def radial_envelope_score(shape):
        bb = shape.BoundingBox()
        dimensions = sorted([bb.xlen, bb.ylen, bb.zlen], reverse=True)
        return dimensions[0] * dimensions[1]

    body_index = max(range(len(solids)), key=lambda i: radial_envelope_score(solids[i]))
    body = solids[body_index]
    preserved_solids = [solid for i, solid in enumerate(solids) if i != body_index]

    bb = body.BoundingBox()
    spans = {"x": bb.xlen, "y": bb.ylen, "z": bb.zlen}
    axis_name = min(spans, key=spans.get)

    centers = {
        "x": 0.5 * (bb.xmin + bb.xmax),
        "y": 0.5 * (bb.ymin + bb.ymax),
        "z": 0.5 * (bb.zmin + bb.zmax)
    }
    minimums = {"x": bb.xmin, "y": bb.ymin, "z": bb.zmin}
    maximums = {"x": bb.xmax, "y": bb.ymax, "z": bb.zmax}

    unit_vectors = {
        "x": cq.Vector(1, 0, 0),
        "y": cq.Vector(0, 1, 0),
        "z": cq.Vector(0, 0, 1)
    }
    radial_names = [name for name in ("x", "y", "z") if name != axis_name]
    radial_1_name, radial_2_name = radial_names
    radial_1 = unit_vectors[radial_1_name]
    radial_2 = unit_vectors[radial_2_name]
    axis_vector = unit_vectors[axis_name]

    axis_min = minimums[axis_name]
    axis_max = maximums[axis_name]
    radial_center_1 = centers[radial_1_name]
    radial_center_2 = centers[radial_2_name]
    axis_center = centers[axis_name]

    radial_span_1 = spans[radial_1_name]
    radial_span_2 = spans[radial_2_name]
    outside_radius = 0.25 * (radial_span_1 + radial_span_2)

    # Retain the existing repeated tooth count and fit a conventional 20-degree
    # full-depth involute spur gear to the original outside envelope.
    tooth_count = 36
    pressure_angle = math.radians(20.0)
    module = (2.0 * outside_radius) / float(tooth_count + 2)
    pitch_radius = 0.5 * module * tooth_count
    base_radius = pitch_radius * math.cos(pressure_angle)
    root_radius = pitch_radius - 1.25 * module

    if root_radius <= 0.0 or outside_radius <= root_radius:
        raise ValueError("Could not derive a valid spur-gear envelope")

    def component(point, name):
        if name == "x":
            return point.x
        if name == "y":
            return point.y
        return point.z

    # Find the original outer-rim axial limits in the detected axis direction.
    # Using vertices well inside the tooth tips includes the complete rim width
    # rather than only the narrow crown of the rounded source teeth.
    outer_axis_coordinates = []
    for vertex in body.Vertices():
        point = vertex.Center()
        u = component(point, radial_1_name) - radial_center_1
        v = component(point, radial_2_name) - radial_center_2
        radius = math.hypot(u, v)
        if radius >= 0.78 * outside_radius:
            outer_axis_coordinates.append(component(point, axis_name))

    if outer_axis_coordinates:
        tooth_axis_min = min(outer_axis_coordinates)
        tooth_axis_max = max(outer_axis_coordinates)
    else:
        tooth_axis_min = axis_min
        tooth_axis_max = axis_max

    face_width = tooth_axis_max - tooth_axis_min
    if face_width <= 1.0e-5:
        tooth_axis_min = axis_min
        tooth_axis_max = axis_max
        face_width = tooth_axis_max - tooth_axis_min

    def make_point(u, v, axial):
        values = {
            radial_1_name: radial_center_1 + u,
            radial_2_name: radial_center_2 + v,
            axis_name: axial
        }
        return cq.Vector(values["x"], values["y"], values["z"])

    def axis_center_point(axial):
        values = {
            radial_1_name: radial_center_1,
            radial_2_name: radial_center_2,
            axis_name: axial
        }
        return cq.Vector(values["x"], values["y"], values["z"])

    # Remove the old rounded peripheral teeth while retaining the complete hub,
    # spline seat, web, openings, ribs, and the continuous inner portion of the rim.
    trim_margin = max(module, 0.25 * face_width, 0.1)
    trim_cylinder = cq.Solid.makeCylinder(
        root_radius,
        (axis_max - axis_min) + 2.0 * trim_margin,
        axis_center_point(axis_min - trim_margin),
        axis_vector
    )
    trimmed_body = body.intersect(trim_cylinder)

    def involute(alpha):
        return math.tan(alpha) - alpha

    pitch_involute = involute(pressure_angle)
    half_pitch_thickness = math.pi / (2.0 * tooth_count)

    def flank_half_angle(radius):
        effective_radius = max(radius, base_radius)
        ratio = max(-1.0, min(1.0, base_radius / effective_radius))
        alpha = math.acos(ratio)
        return half_pitch_thickness + pitch_involute - involute(alpha)

    angular_pitch = 2.0 * math.pi / tooth_count
    flank_start_radius = max(root_radius, base_radius)
    half_at_base = flank_half_angle(flank_start_radius)
    half_at_tip = flank_half_angle(outside_radius)

    flank_samples = 10
    tip_samples = 3
    root_samples = 4
    profile_points = []

    for tooth in range(tooth_count):
        center_angle = tooth * angular_pitch

        profile_points.append(make_point(
            root_radius * math.cos(center_angle - half_at_base),
            root_radius * math.sin(center_angle - half_at_base),
            tooth_axis_min
        ))

        for sample in range(flank_samples):
            fraction = sample / float(flank_samples - 1)
            radius = flank_start_radius + fraction * (outside_radius - flank_start_radius)
            angle = center_angle - flank_half_angle(radius)
            profile_points.append(make_point(
                radius * math.cos(angle), radius * math.sin(angle), tooth_axis_min
            ))

        for sample in range(1, tip_samples + 1):
            fraction = sample / float(tip_samples)
            angle = center_angle - half_at_tip + fraction * (2.0 * half_at_tip)
            profile_points.append(make_point(
                outside_radius * math.cos(angle),
                outside_radius * math.sin(angle),
                tooth_axis_min
            ))

        for sample in range(1, flank_samples):
            fraction = sample / float(flank_samples - 1)
            radius = outside_radius - fraction * (outside_radius - flank_start_radius)
            angle = center_angle + flank_half_angle(radius)
            profile_points.append(make_point(
                radius * math.cos(angle), radius * math.sin(angle), tooth_axis_min
            ))

        profile_points.append(make_point(
            root_radius * math.cos(center_angle + half_at_base),
            root_radius * math.sin(center_angle + half_at_base),
            tooth_axis_min
        ))

        root_start = center_angle + half_at_base
        next_root_end = center_angle + angular_pitch - half_at_base
        for sample in range(1, root_samples + 1):
            fraction = sample / float(root_samples)
            angle = root_start + fraction * (next_root_end - root_start)
            profile_points.append(make_point(
                root_radius * math.cos(angle),
                root_radius * math.sin(angle),
                tooth_axis_min
            ))

    outer_wire = cq.Wire.makePolygon(profile_points, close=True)

    # Use a narrow annular replacement band with radial overlap for a reliable
    # union without filling any original web openings.
    radial_overlap = max(0.35 * module, 0.08)
    inner_radius = max(0.1, root_radius - radial_overlap)
    inner_wire = cq.Wire.makeCircle(
        inner_radius,
        axis_center_point(tooth_axis_min),
        axis_vector
    )

    gear_face = cq.Face.makeFromWires(outer_wire, [inner_wire])
    spur_band = cq.Solid.extrudeLinear(
        gear_face,
        axis_vector.multiply(face_width)
    )

    modified_body = trimmed_body.fuse(spur_band)
    try:
        modified_body = modified_body.clean()
    except Exception:
        pass

    if not modified_body.isValid():
        raise ValueError("The modified sprocket body is not a valid solid")

    final_solids = [modified_body] + preserved_solids
    if len(final_solids) == 1:
        result = final_solids[0]
    else:
        result = cq.Compound.makeCompound(final_solids)

    print("Converted rounded peripheral teeth to straight involute spur teeth")
    print("Detected rotation axis: %s" % axis_name.upper())
    print("Tooth count: %d" % tooth_count)
    print("Pressure angle: 20 degrees")
    print("Fitted module: %.6f mm" % module)
    print("Outside diameter: %.6f mm" % (2.0 * outside_radius))
    print("Root diameter: %.6f mm" % (2.0 * root_radius))
    print("Axial tooth width: %.6f mm" % face_width)
    print("Preserved separate solids: %d" % len(preserved_solids))
    print("Output validity: %s" % result.isValid())
    return result