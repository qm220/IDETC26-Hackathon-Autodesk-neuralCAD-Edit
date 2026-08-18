def my_cad_function(args):
    import os
    import math

    input_file = os.path.expanduser(args['input_file'])
    model = cq.importers.importStep(input_file)
    source_shape = model.val()

    # Identify the four thin, diagonal link-arm solids. The rails and pins are
    # retained directly from the imported model.
    all_solids = list(source_shape.Solids())
    link_indices = []
    for i, solid in enumerate(all_solids):
        bb = solid.BoundingBox()
        if (
            1.5 <= bb.zlen <= 2.5
            and bb.xlen > 70.0
            and bb.ylen > 35.0
            and solid.Volume() < 2500.0
        ):
            link_indices.append(i)

    print('=== LINK PROFILE MODIFICATION ===')
    print('Input valid:', source_shape.isValid())
    print('Input solid count:', len(all_solids))
    print('Detected link-arm solid indices:', link_indices)

    if len(link_indices) != 4:
        raise ValueError(
            'Expected four thin diagonal link-arm solids, but detected %d: %s'
            % (len(link_indices), link_indices)
        )

    # The original link bores are 5 mm in diameter. Interpret the requested
    # unsigned 1 mm change as an increase, giving 6 mm bores. Increase the
    # corresponding capsule diameter by the same 1 mm to preserve the original
    # radial ligament. Original eye diameter is approximately 8.8 mm.
    original_hole_diameter = 5.0
    diameter_change = 1.0
    new_hole_diameter = original_hole_diameter + diameter_change
    original_outer_eye_diameter = 8.8
    new_capsule_width = original_outer_eye_diameter + diameter_change
    capsule_radius = new_capsule_width / 2.0
    hole_radius = new_hole_diameter / 2.0

    def find_three_bore_centers(solid):
        bb = solid.BoundingBox()
        candidates = []
        for face in solid.Faces():
            try:
                if face.geomType() != 'CYLINDER':
                    continue
                fb = face.BoundingBox()
                # Through-bore cylindrical walls are approximately 5 x 5 x 2 mm.
                if (
                    4.5 <= fb.xlen <= 5.5
                    and 4.5 <= fb.ylen <= 5.5
                    and fb.zlen >= 0.75 * bb.zlen
                ):
                    c = face.Center()
                    point = (c.x, c.y)
                    if not any(
                        math.hypot(point[0] - p[0], point[1] - p[1]) < 0.1
                        for p in candidates
                    ):
                        candidates.append(point)
            except Exception:
                pass

        if len(candidates) != 3:
            raise ValueError(
                'Could not uniquely identify three bores in link at z=(%.3f, %.3f); found %s'
                % (bb.zmin, bb.zmax, candidates)
            )
        return candidates

    def make_capsule_link(solid):
        bb = solid.BoundingBox()
        thickness = bb.zlen
        z0 = bb.zmin
        centers = find_three_bore_centers(solid)

        # The two points with the greatest separation are the end pivots.
        pairs = []
        for a in range(3):
            for b in range(a + 1, 3):
                d = math.hypot(
                    centers[b][0] - centers[a][0],
                    centers[b][1] - centers[a][1]
                )
                pairs.append((d, a, b))
        _, ia, ib = max(pairs)
        p1 = centers[ia]
        p2 = centers[ib]

        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        length = math.hypot(dx, dy)
        if length < 1.0:
            raise ValueError('Degenerate link endpoint spacing')

        nx = -dy / length
        ny = dx / length
        r = capsule_radius
        corners = [
            (p1[0] + nx * r, p1[1] + ny * r),
            (p2[0] + nx * r, p2[1] + ny * r),
            (p2[0] - nx * r, p2[1] - ny * r),
            (p1[0] - nx * r, p1[1] - ny * r)
        ]

        wp = cq.Workplane('XY', origin=(0, 0, z0))
        middle = wp.polyline(corners).close().extrude(thickness)
        end1 = cq.Workplane('XY', origin=(0, 0, z0)).center(p1[0], p1[1]).circle(r).extrude(thickness)
        end2 = cq.Workplane('XY', origin=(0, 0, z0)).center(p2[0], p2[1]).circle(r).extrude(thickness)
        result = middle.union(end1).union(end2)

        # Preserve all three original pivot axes and cut the revised 6 mm holes.
        result = (
            result.faces('>Z')
            .workplane()
            .pushPoints(centers)
            .circle(hole_radius)
            .cutThruAll()
        )

        print(
            'Rebuilt link: z=(%.3f, %.3f), endpoints=%s / %s, center set=%s, '
            'capsule width=%.3f, hole diameter=%.3f'
            % (z0, z0 + thickness, p1, p2, centers,
               new_capsule_width, new_hole_diameter)
        )
        return result.val()

    output_solids = []
    for i, solid in enumerate(all_solids):
        if i in link_indices:
            output_solids.append(make_capsule_link(solid))
        else:
            output_solids.append(solid)

    output = cq.Compound.makeCompound(output_solids)
    print('Output valid:', output.isValid())
    print('Output solid count:', len(output.Solids()))
    print('Applied hole diameter change: %.3f mm -> %.3f mm'
          % (original_hole_diameter, new_hole_diameter))
    print('Applied long-hole capsule width: %.3f mm' % new_capsule_width)

    return cq.Workplane('XY').newObject([output])