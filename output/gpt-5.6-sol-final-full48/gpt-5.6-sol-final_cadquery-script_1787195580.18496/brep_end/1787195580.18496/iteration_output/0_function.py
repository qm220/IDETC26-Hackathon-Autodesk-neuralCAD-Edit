def my_cad_function(args):
    import os
    import math

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    source_shape = imported.val() if hasattr(imported, "val") else imported
    solids = list(source_shape.Solids())
    if not solids:
        raise ValueError("The input STEP file contains no solids")

    # Identify the sprocket body as the solid with the largest XY envelope.
    def xy_span(shape):
        bb = shape.BoundingBox()
        return max(bb.xlen, bb.ylen)

    body_index = max(range(len(solids)), key=lambda i: xy_span(solids[i]))
    body = solids[body_index]
    preserved_solids = [s for i, s in enumerate(solids) if i != body_index]

    bb = body.BoundingBox()
    cx = 0.5 * (bb.xmin + bb.xmax)
    cy = 0.5 * (bb.ymin + bb.ymax)
    body_zmin = bb.zmin
    body_zmax = bb.zmax

    # The reference is visually a 36-tooth sprocket. Retain that repetition and
    # fit a conventional 20-degree, full-depth spur gear to its outside envelope.
    tooth_count = 36
    pressure_angle = math.radians(20.0)
    outside_radius = 0.25 * (bb.xlen + bb.ylen)
    module = (2.0 * outside_radius) / float(tooth_count + 2)
    pitch_radius = 0.5 * module * tooth_count
    base_radius = pitch_radius * math.cos(pressure_angle)
    root_radius = pitch_radius - 1.25 * module

    if root_radius <= 0 or outside_radius <= root_radius:
        raise ValueError("Could not derive a valid spur-gear envelope")

    # Determine the retained face width from vertices in the original outer rim.
    # This excludes the separate center insert while retaining the maximum rim width.
    outer_z = []
    for vertex in body.Vertices():
        p = vertex.Center()
        radius = math.hypot(p.x - cx, p.y - cy)
        if radius >= 0.78 * outside_radius:
            outer_z.append(p.z)

    if outer_z:
        tooth_zmin = min(outer_z)
        tooth_zmax = max(outer_z)
    else:
        tooth_zmin = body_zmin
        tooth_zmax = body_zmax

    face_width = tooth_zmax - tooth_zmin
    if face_width <= 1.0e-5:
        tooth_zmin = body_zmin
        tooth_zmax = body_zmax
        face_width = tooth_zmax - tooth_zmin

    # Trim away every old rounded tooth and crown while retaining the web, hub,
    # openings, ribs, and the continuous portion of the original annular rim.
    trim_margin = max(module, 0.05 * face_width)
    trim_cylinder = cq.Solid.makeCylinder(
        root_radius,
        (body_zmax - body_zmin) + 2.0 * trim_margin,
        cq.Vector(cx, cy, body_zmin - trim_margin),
        cq.Vector(0, 0, 1)
    )
    trimmed_body = body.intersect(trim_cylinder)

    # Standard involute functions. Zero profile shift and zero intentional
    # backlash are used because no mating-gear specification was supplied.
    def involute(alpha):
        return math.tan(alpha) - alpha

    pitch_inv = involute(pressure_angle)
    half_pitch_thickness = math.pi / (2.0 * tooth_count)

    def flank_half_angle(radius):
        effective_radius = max(radius, base_radius)
        ratio = min(1.0, max(-1.0, base_radius / effective_radius))
        alpha = math.acos(ratio)
        return half_pitch_thickness + pitch_inv - involute(alpha)

    # Build one continuous, counter-clockwise involute outer profile. The profile
    # is then extruded without taper, crown, twist, chamfer, or axial edge rounds.
    flank_samples = 9
    tip_samples = 3
    root_samples = 3
    angular_pitch = 2.0 * math.pi / tooth_count
    flank_start_radius = max(root_radius, base_radius)
    half_at_base = flank_half_angle(flank_start_radius)
    half_at_tip = flank_half_angle(outside_radius)
    outer_points = []

    for tooth in range(tooth_count):
        center_angle = tooth * angular_pitch

        # Lower root and lower involute flank, moving radially outward.
        outer_points.append((
            cx + root_radius * math.cos(center_angle - half_at_base),
            cy + root_radius * math.sin(center_angle - half_at_base)
        ))
        for j in range(flank_samples):
            fraction = j / float(flank_samples - 1)
            radius = flank_start_radius + fraction * (outside_radius - flank_start_radius)
            angle = center_angle - flank_half_angle(radius)
            outer_points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))

        # Flat-radius addendum arc across the tooth tip.
        for j in range(1, tip_samples + 1):
            fraction = j / float(tip_samples)
            angle = center_angle - half_at_tip + fraction * (2.0 * half_at_tip)
            outer_points.append((
                cx + outside_radius * math.cos(angle),
                cy + outside_radius * math.sin(angle)
            ))

        # Upper involute flank, moving back toward the root.
        for j in range(1, flank_samples):
            fraction = j / float(flank_samples - 1)
            radius = outside_radius - fraction * (outside_radius - flank_start_radius)
            angle = center_angle + flank_half_angle(radius)
            outer_points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))

        outer_points.append((
            cx + root_radius * math.cos(center_angle + half_at_base),
            cy + root_radius * math.sin(center_angle + half_at_base)
        ))

        # Root arc leading to the following tooth.
        next_lower_angle = center_angle + angular_pitch - half_at_base
        root_angle_start = center_angle + half_at_base
        for j in range(1, root_samples + 1):
            fraction = j / float(root_samples)
            angle = root_angle_start + fraction * (next_lower_angle - root_angle_start)
            outer_points.append((
                cx + root_radius * math.cos(angle),
                cy + root_radius * math.sin(angle)
            ))

    outer_wire = cq.Wire.makePolygon(
        [cq.Vector(x, y, 0) for x, y in outer_points],
        close=True
    )

    # Restrict replacement material to a narrow annular band so none of the
    # original web openings or spokes are filled. A small radial overlap makes
    # the new spur rim fuse reliably to the trimmed original body.
    radial_overlap = max(0.35 * module, 0.05)
    inner_radius = max(0.1, root_radius - radial_overlap)
    inner_wire = cq.Wire.makeCircle(
        inner_radius,
        cq.Vector(cx, cy, 0),
        cq.Vector(0, 0, 1)
    )
    gear_face = cq.Face.makeFromWires(outer_wire, [inner_wire])
    spur_band = cq.Solid.extrudeLinear(gear_face, cq.Vector(0, 0, face_width))
    spur_band = spur_band.translate(cq.Vector(0, 0, tooth_zmin))

    modified_body = trimmed_body.fuse(spur_band)
    try:
        modified_body = modified_body.clean()
    except Exception:
        pass

    if not modified_body.isValid():
        raise ValueError("The modified sprocket body is not a valid solid")

    # Preserve the original center insert and any other source solids as separate
    # solids rather than fusing them to the edited sprocket body.
    final_solids = [modified_body] + preserved_solids
    if len(final_solids) == 1:
        result = final_solids[0]
    else:
        result = cq.Compound.makeCompound(final_solids)

    print("Converted rounded peripheral teeth to straight involute spur teeth")
    print("Tooth count: %d" % tooth_count)
    print("Assumed pressure angle: 20 degrees")
    print("Assumed profile shift: 0")
    print("Assumed intentional backlash: 0 mm")
    print("Fitted module: %.6f mm" % module)
    print("Outside diameter: %.6f mm" % (2.0 * outside_radius))
    print("Root diameter: %.6f mm" % (2.0 * root_radius))
    print("Face width: %.6f mm" % face_width)
    print("Output solids: %d" % len(final_solids))
    print("Output validity: %s" % result.isValid())
    return result