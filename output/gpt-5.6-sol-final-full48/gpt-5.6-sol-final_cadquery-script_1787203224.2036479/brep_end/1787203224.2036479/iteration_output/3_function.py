def my_cad_function(args):
    import cadquery as cq
    import math

    model = cq.importers.importStep(args["input_file"])
    root = model.val()
    solids = list(root.Solids()) if hasattr(root, "Solids") else model.solids().vals()

    if len(solids) < 3:
        raise ValueError("Expected two blade solids and a central hub solid")

    def dimensions(shape):
        bb = shape.BoundingBox()
        return bb.xlen, bb.ylen, bb.zlen

    # Identify the two original elongated blade members independently of their
    # orientation. All compact solids belong to the hub/axle and are preserved.
    ranked = sorted(solids, key=lambda s: max(dimensions(s)), reverse=True)
    blade_candidates = ranked[:2]
    preserved = ranked[2:]

    if preserved:
        center_shape = max(preserved, key=lambda s: s.Volume())
        center = center_shape.Center()
    else:
        center = root.Center()
    cx, cy, cz = center.x, center.y, center.z

    def radius_long_edges(shape):
        # The requested four edges are the straight longitudinal boundary
        # edges. Excluding curved edges avoids selecting bore seams and ends.
        candidates = []
        for edge in shape.Edges():
            try:
                is_line = edge.geomType() == "LINE"
            except Exception:
                is_line = True
            if is_line and edge.Length() > 60.0:
                candidates.append(edge)

        if not candidates:
            return shape

        # Prefer a common operation so all four edges receive equal radii.
        for radius in (0.60, 0.50, 0.40, 0.30):
            try:
                result = cq.Workplane(obj=shape).newObject(candidates).fillet(radius).val()
                if result.Volume() > 0:
                    return result
            except Exception:
                pass
        return shape

    original_blades = [radius_long_edges(s) for s in blade_candidates]

    def blade_axis_angle(shape):
        # Determine the blade direction from remote geometry. Using only the
        # most distant vertices prevents central holes and blends from skewing
        # the angle, which occurred with whole-shape PCA.
        samples = []
        max_radius = 0.0
        for vertex in shape.Vertices():
            p = vertex.Center()
            dx, dz = p.x - cx, p.z - cz
            radius = math.hypot(dx, dz)
            samples.append((dx, dz, radius))
            max_radius = max(max_radius, radius)

        remote = [p for p in samples if p[2] >= 0.72 * max_radius]
        if not remote:
            return 0.0

        # Double-angle averaging treats opposite arms as the same axis.
        sum_cos = 0.0
        sum_sin = 0.0
        for dx, dz, radius in remote:
            angle = math.atan2(dz, dx)
            sum_cos += math.cos(2.0 * angle)
            sum_sin += math.sin(2.0 * angle)

        axis = 0.5 * math.atan2(sum_sin, sum_cos)
        return math.degrees(axis) % 180.0

    def axis_distance(a, b):
        delta = abs((a - b) % 180.0)
        return min(delta, 180.0 - delta)

    existing_angles = [blade_axis_angle(s) for s in original_blades]

    # Select the open axis having maximum angular clearance. With the original
    # approximately 60-degree spacing this completes an even six-arm rotor.
    best_angle = 0.0
    best_clearance = -1.0
    for index in range(3600):
        candidate = index * 0.05
        clearance = min(axis_distance(candidate, a) for a in existing_angles)
        if clearance > best_clearance:
            best_clearance = clearance
            best_angle = candidate

    # Duplicate the longer established blade design and rotate it about the
    # unchanged common Y-axis.
    source_index = max(
        range(2),
        key=lambda i: max(dimensions(original_blades[i]))
    )
    source = original_blades[source_index]
    rotation = best_angle - existing_angles[source_index]
    third_blade = source.rotate(
        (cx, cy, cz),
        (cx, cy + 1.0, cz),
        rotation
    )

    def transition_envelope(shape, layer_center):
        bb = shape.BoundingBox()
        half_thickness = 0.21
        inner_radius = 18.0
        outer_radius = 29.0
        far_radius = max(bb.xlen, bb.zlen) + 50.0

        full_low = bb.ymin - 0.02
        full_high = bb.ymax + 0.02
        thin_low = layer_center - half_thickness
        thin_high = layer_center + half_thickness

        # Revolving this X/Y profile about local Y creates an axisymmetric
        # central 0.42 mm layer with gradual transitions to full arm thickness.
        profile = [
            (0.0, thin_low),
            (inner_radius, thin_low),
            (outer_radius, full_low),
            (far_radius, full_low),
            (far_radius, full_high),
            (outer_radius, full_high),
            (inner_radius, thin_high),
            (0.0, thin_high)
        ]
        return (
            cq.Workplane("XY", origin=(cx, cy, cz))
            .polyline(profile)
            .close()
            .revolve(360.0, (0.0, 0.0), (0.0, 1.0), combine=False)
            .val()
        )

    # The two existing members occupy the outside layers. The newly created
    # blade is explicitly placed through the middle of the three-layer stack.
    blades_and_layers = [
        (original_blades[0], cy - 0.46),
        (third_blade, cy),
        (original_blades[1], cy + 0.46)
    ]

    thinned_blades = []
    for blade, layer_center in blades_and_layers:
        envelope = transition_envelope(blade, layer_center)
        try:
            thinned = blade.intersect(envelope)
            if thinned.Volume() <= 0:
                raise ValueError("Central thinning produced an empty blade")
            thinned_blades.append(thinned)
        except Exception:
            # Robust fallback retaining the complete outer arms while replacing
            # only the hub-overlap region with a nominal 0.42 mm layer.
            cutter = cq.Solid.makeCylinder(
                24.0,
                200.0,
                cq.Vector(cx, cy - 100.0, cz),
                cq.Vector(0.0, 1.0, 0.0)
            )
            slab = (
                cq.Workplane("XZ", origin=(cx, layer_center, cz))
                .box(2000.0, 2000.0, 0.42, centered=(True, True, True))
                .val()
            )
            outer = blade.cut(cutter)
            center_piece = blade.intersect(cutter).intersect(slab)
            thinned_blades.append(cq.Compound.makeCompound([outer, center_piece]))

    result = cq.Compound.makeCompound(preserved + thinned_blades)
    return cq.Workplane(obj=result)