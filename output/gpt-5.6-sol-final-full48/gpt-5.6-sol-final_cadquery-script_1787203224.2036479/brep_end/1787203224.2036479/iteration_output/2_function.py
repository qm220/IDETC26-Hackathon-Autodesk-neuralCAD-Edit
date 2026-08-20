def my_cad_function(args):
    import cadquery as cq
    import math

    model = cq.importers.importStep(args["input_file"])
    root = model.val()
    solids = list(root.Solids()) if hasattr(root, "Solids") else model.solids().vals()

    if len(solids) < 3:
        raise ValueError("Expected at least two blade solids and one central hub solid")

    def dimensions(shape):
        bb = shape.BoundingBox()
        return bb.xlen, bb.ylen, bb.zlen

    # The blade members are the solids having a long dimension, while the
    # compact remaining solid(s) form the original hub and axle assembly.
    blade_candidates = []
    preserved = []
    for shape in solids:
        dims = dimensions(shape)
        if max(dims) > 80.0:
            blade_candidates.append(shape)
        else:
            preserved.append(shape)

    if len(blade_candidates) < 2:
        ranked = sorted(solids, key=lambda s: max(dimensions(s)), reverse=True)
        blade_candidates = ranked[:2]
        preserved = ranked[2:]
    else:
        blade_candidates = sorted(
            blade_candidates,
            key=lambda s: max(dimensions(s)),
            reverse=True
        )[:2]
        preserved = [s for s in solids if all(not s.isSame(b) for b in blade_candidates)]

    # Use the compact hub to recover the fixed rotor center.
    center_shape = max(preserved, key=lambda s: s.Volume()) if preserved else root
    c = center_shape.Center()
    cx, cy, cz = c.x, c.y, c.z

    def add_long_edge_radii(shape):
        # Select only genuinely longitudinal edges, avoiding end holes and
        # short central details. Try progressively smaller manufacturing radii.
        long_edges = [e for e in shape.Edges() if e.Length() > 60.0]
        if not long_edges:
            return shape
        for radius in (0.60, 0.45, 0.30):
            try:
                return cq.Workplane(obj=shape).newObject(long_edges).fillet(radius).val()
            except Exception:
                pass
        return shape

    radiused_originals = [add_long_edge_radii(s) for s in blade_candidates]

    def principal_angle_xz(shape):
        pts = []
        for v in shape.Vertices():
            p = v.Center()
            pts.append((p.x - cx, p.z - cz))
        if len(pts) < 2:
            return 0.0
        mx = sum(p[0] for p in pts) / len(pts)
        mz = sum(p[1] for p in pts) / len(pts)
        xx = sum((p[0] - mx) ** 2 for p in pts)
        zz = sum((p[1] - mz) ** 2 for p in pts)
        xz = sum((p[0] - mx) * (p[1] - mz) for p in pts)
        angle = math.degrees(0.5 * math.atan2(2.0 * xz, xx - zz))
        return angle % 180.0

    def line_angle_distance(a, b):
        d = abs((a - b) % 180.0)
        return min(d, 180.0 - d)

    existing_angles = [principal_angle_xz(s) for s in radiused_originals]

    # Find the unused orientation that maximizes clearance from both existing
    # double-ended blades. This produces the symmetric six-arm arrangement.
    best_angle = 0.0
    best_clearance = -1.0
    for i in range(1800):
        candidate = i / 10.0
        clearance = min(line_angle_distance(candidate, a) for a in existing_angles)
        if clearance > best_clearance:
            best_clearance = clearance
            best_angle = candidate

    source_index = max(
        range(len(radiused_originals)),
        key=lambda i: max(dimensions(radiused_originals[i]))
    )
    source = radiused_originals[source_index]
    rotation = best_angle - existing_angles[source_index]
    third_blade = source.rotate(
        (cx, cy, cz),
        (cx, cy + 1.0, cz),
        rotation
    )

    def make_transition_envelope(shape, layer_center):
        bb = shape.BoundingBox()
        central_half = 0.21       # exact nominal central thickness: 0.42 mm
        inner_radius = 18.0
        outer_radius = 28.0
        far_radius = max(bb.xlen, bb.zlen) * 1.2 + 20.0

        full_low = bb.ymin - 0.02
        full_high = bb.ymax + 0.02
        thin_low = layer_center - central_half
        thin_high = layer_center + central_half

        # A revolved radial envelope creates a constant 0.42 mm center and a
        # gradual transition back to the preserved full-thickness outer arms.
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
        envelope = (
            cq.Workplane("XY", origin=(cx, cy, cz))
            .polyline(profile)
            .close()
            .revolve(360.0, (0.0, 0.0), (0.0, 1.0), combine=False)
            .val()
        )
        return envelope

    # Three separate 0.42 mm center layers with small assembly clearances.
    layer_centers = [cy - 0.46, cy, cy + 0.46]
    all_blades = [radiused_originals[0], radiused_originals[1], third_blade]
    thinned_blades = []
    for blade, layer_center in zip(all_blades, layer_centers):
        envelope = make_transition_envelope(blade, layer_center)
        try:
            thinned = blade.intersect(envelope)
            if thinned.Volume() <= 0:
                raise ValueError("Empty blade after central thinning")
            thinned_blades.append(thinned)
        except Exception:
            # Conservative fallback: retain full outer geometry and replace the
            # central circular portion with a 0.42 mm layer.
            cutter = cq.Solid.makeCylinder(
                24.0,
                200.0,
                cq.Vector(cx, cy - 100.0, cz),
                cq.Vector(0.0, 1.0, 0.0)
            )
            slab = cq.Workplane("XY", origin=(cx, layer_center, cz)).box(
                2000.0, 0.42, 2000.0,
                centered=(True, True, True)
            ).val()
            outer = blade.cut(cutter)
            center_piece = blade.intersect(cutter).intersect(slab)
            thinned_blades.append(cq.Compound.makeCompound([outer, center_piece]))

    result_shapes = preserved + thinned_blades
    result = cq.Compound.makeCompound(result_shapes)
    return cq.Workplane(obj=result)
