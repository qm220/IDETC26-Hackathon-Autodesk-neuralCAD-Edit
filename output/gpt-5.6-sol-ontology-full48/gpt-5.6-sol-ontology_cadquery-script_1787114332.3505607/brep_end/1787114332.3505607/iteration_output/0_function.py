def my_cad_function(args):
    import os
    import math

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    model = imported.val() if hasattr(imported, "val") else imported

    print("Loaded STEP:", input_file)
    print("Model valid:", model.isValid())
    print("Global face count:", len(model.Faces()))

    # Bind the planning-stage FACE N references to the actual imported topology.
    faces = list(model.Faces())
    reference_indices = [513, 593, 670, 671, 672, 673, 779]
    for idx in reference_indices:
        if idx < len(faces):
            face = faces[idx]
            c = face.Center()
            bb = face.BoundingBox()
            try:
                gt = face.geomType()
            except Exception:
                gt = "UNKNOWN"
            print(
                "FACE %d: type=%s area=%.6f center=(%.6f, %.6f, %.6f) "
                "bbox=(%.6f, %.6f, %.6f)-(%.6f, %.6f, %.6f)"
                % (
                    idx, gt, face.Area(), c.x, c.y, c.z,
                    bb.xmin, bb.ymin, bb.zmin,
                    bb.xmax, bb.ymax, bb.zmax,
                )
            )

    solids = list(model.Solids())
    if len(solids) < 2:
        raise ValueError("Expected the two-solid sprocket and insert model")

    # SOLID 1 is selected geometrically as the solid with the greatest radial span.
    def radial_extent(shape):
        radii = []
        for vertex in shape.Vertices():
            p = vertex.Center()
            radii.append(math.hypot(p.x, p.z))
        if radii:
            return max(radii)
        bb = shape.BoundingBox()
        return max(
            math.hypot(x, z)
            for x in (bb.xmin, bb.xmax)
            for z in (bb.zmin, bb.zmax)
        )

    solid_data = []
    for i, solid in enumerate(solids):
        bb = solid.BoundingBox()
        rext = radial_extent(solid)
        solid_data.append((rext, solid))
        print(
            "Solid %d: volume=%.6f radial_extent=%.6f "
            "bbox=(%.6f, %.6f, %.6f)-(%.6f, %.6f, %.6f)"
            % (
                i, solid.Volume(), rext,
                bb.xmin, bb.ymin, bb.zmin,
                bb.xmax, bb.ymax, bb.zmax,
            )
        )

    solid_data.sort(key=lambda item: item[0], reverse=True)
    sprocket = solid_data[0][1]
    preserved_solids = [item[1] for item in solid_data[1:]]

    sprocket_bb = sprocket.BoundingBox()
    y_min = sprocket_bb.ymin
    y_max = sprocket_bb.ymax
    face_width = y_max - y_min
    outside_radius = radial_extent(sprocket)

    tooth_count = 27
    pressure_angle = math.radians(20.0)

    # With no replacement dimensions supplied, fit a standard full-depth
    # 27-tooth involute definition to the existing maximum radial envelope.
    module = (2.0 * outside_radius) / float(tooth_count + 2)
    pitch_radius = module * tooth_count / 2.0
    base_radius = pitch_radius * math.cos(pressure_angle)
    addendum_radius = outside_radius
    root_radius = pitch_radius - 1.25 * module

    if root_radius <= 0.0 or root_radius >= addendum_radius:
        raise ValueError("Derived spur gear radii are invalid")

    print(
        "Derived spur gear: teeth=%d module=%.6f pressure_angle=20deg "
        "root_r=%.6f base_r=%.6f pitch_r=%.6f outside_r=%.6f "
        "face_width=%.6f y=[%.6f, %.6f]"
        % (
            tooth_count, module, root_radius, base_radius,
            pitch_radius, addendum_radius, face_width, y_min, y_max,
        )
    )

    # Align the new pattern with the representative original tooth-tip face.
    phase = 0.0
    if 671 < len(faces):
        tip_center = faces[671].Center()
        tip_radius = math.hypot(tip_center.x, tip_center.z)
        if tip_radius > 0.65 * outside_radius:
            phase = math.atan2(tip_center.z, tip_center.x)
    print("Pattern phase (degrees):", math.degrees(phase))

    # Suppress all of F009 by clipping the sprocket to a continuous root blank.
    # A small radial overlap is retained for robust tooth-to-rim union.
    trim_radius = root_radius + min(0.15, 0.04 * module)
    axial_pad = max(0.2, 0.05 * face_width)
    trim_cylinder = cq.Solid.makeCylinder(
        trim_radius,
        face_width + 2.0 * axial_pad,
        cq.Vector(0.0, y_min - axial_pad, 0.0),
        cq.Vector(0.0, 1.0, 0.0),
    )
    trimmed_sprocket = sprocket.intersect(trim_cylinder)
    if trimmed_sprocket.isNull():
        raise ValueError("Root-envelope trimming removed the sprocket")

    def involute_function(alpha):
        return math.tan(alpha) - alpha

    inv_pressure = involute_function(pressure_angle)
    half_tooth_at_pitch = math.pi / (2.0 * tooth_count)
    base_half_angle = half_tooth_at_pitch + inv_pressure

    # Start each additive tooth slightly inside the retained root cylinder.
    join_radius = root_radius - min(0.35, 0.08 * module)
    flank_start_radius = max(base_radius, root_radius)
    flank_samples = 9

    def half_angle_at_radius(radius):
        if radius <= base_radius:
            return base_half_angle
        alpha = math.acos(max(-1.0, min(1.0, base_radius / radius)))
        return half_tooth_at_pitch + inv_pressure - involute_function(alpha)

    tooth_solids = []
    pitch_angle = 2.0 * math.pi / tooth_count

    for tooth_index in range(tooth_count):
        center_angle = phase + tooth_index * pitch_angle
        points_2d = []

        # Negative-angle root and base connection.
        points_2d.append((
            join_radius * math.cos(center_angle - base_half_angle),
            join_radius * math.sin(center_angle - base_half_angle),
        ))
        if flank_start_radius > join_radius + 1.0e-7:
            points_2d.append((
                flank_start_radius * math.cos(center_angle - half_angle_at_radius(flank_start_radius)),
                flank_start_radius * math.sin(center_angle - half_angle_at_radius(flank_start_radius)),
            ))

        # First involute flank, from base/root region to addendum.
        for j in range(1, flank_samples + 1):
            fraction = float(j) / float(flank_samples)
            radius = flank_start_radius + fraction * (addendum_radius - flank_start_radius)
            angle = center_angle - half_angle_at_radius(radius)
            points_2d.append((radius * math.cos(angle), radius * math.sin(angle)))

        # A direct segment between the two addendum endpoints forms a flat
        # top land rather than the original cylindrical rounded sprocket lobe.
        tip_half_angle = half_angle_at_radius(addendum_radius)
        points_2d.append((
            addendum_radius * math.cos(center_angle + tip_half_angle),
            addendum_radius * math.sin(center_angle + tip_half_angle),
        ))

        # Opposing involute flank, descending toward the root.
        for j in range(flank_samples - 1, -1, -1):
            fraction = float(j) / float(flank_samples)
            radius = flank_start_radius + fraction * (addendum_radius - flank_start_radius)
            angle = center_angle + half_angle_at_radius(radius)
            points_2d.append((radius * math.cos(angle), radius * math.sin(angle)))

        points_2d.append((
            join_radius * math.cos(center_angle + base_half_angle),
            join_radius * math.sin(center_angle + base_half_angle),
        ))

        # Map transverse XZ coordinates into 3D at the rear axial limit and
        # extrude linearly along +Y, producing straight, untwisted spur traces.
        polygon_vertices = [cq.Vector(x, y_min, z) for x, z in points_2d]
        polygon_vertices.append(polygon_vertices[0])
        tooth_wire = cq.Wire.makePolygon(polygon_vertices)
        tooth_face = cq.Face.makeFromWires(tooth_wire)
        tooth_solid = cq.Solid.extrudeLinear(
            tooth_face,
            cq.Vector(0.0, face_width, 0.0),
        )
        tooth_solids.append(tooth_solid)

    # Unite all 27 replacement teeth to the retained F008 rim in one operation.
    tooth_compound = cq.Compound.makeCompound(tooth_solids)
    rebuilt_sprocket = trimmed_sprocket.fuse(tooth_compound)

    # Clean coincident splitter faces where supported by the installed CQ build.
    try:
        rebuilt_sprocket = rebuilt_sprocket.clean()
    except Exception as exc:
        print("Non-fatal clean warning:", exc)

    print("Rebuilt sprocket valid:", rebuilt_sprocket.isValid())
    print("Rebuilt sprocket solids:", len(rebuilt_sprocket.Solids()))
    print("Rebuilt sprocket volume:", rebuilt_sprocket.Volume())

    if not rebuilt_sprocket.isValid():
        raise ValueError("The rebuilt spur gear is not a valid B-rep")

    # Keep the splined insert as a separate solid and restore the two-component
    # assembly as a compound, without modifying R01, R02, or R03 internally.
    output_solids = list(rebuilt_sprocket.Solids()) + preserved_solids
    result = cq.Compound.makeCompound(output_solids)
    print("Final compound solids:", len(result.Solids()))
    print("Final model valid:", result.isValid())
    return result
