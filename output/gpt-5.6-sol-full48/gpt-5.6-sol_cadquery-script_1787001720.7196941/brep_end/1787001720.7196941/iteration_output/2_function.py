def my_cad_function(args):
    import os
    import math
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    source_shape = imported.val()
    solids = list(source_shape.Solids())

    if len(solids) < 2:
        raise ValueError(
            f"Expected the original two-solid model, but found {len(solids)} solid(s)"
        )

    # Identify the sprocket body by volume and preserve the separate spline insert.
    main_solid = max(solids, key=lambda s: s.Volume())
    insert_solids = [s for s in solids if s is not main_solid]
    bb = main_solid.BoundingBox()

    # The imported model's rotational axis is global Y.
    center_x = 0.5 * (bb.xmin + bb.xmax)
    center_z = 0.5 * (bb.zmin + bb.zmax)
    y_min = bb.ymin
    y_max = bb.ymax
    face_width = y_max - y_min
    outside_radius = 0.5 * max(bb.xlen, bb.zlen)

    # Dimensions and count measured from the existing sprocket envelope.
    tooth_count = 28
    root_radius = 49.55
    ring_inner_radius = 46.80

    if outside_radius <= root_radius:
        raise ValueError("Detected outside radius is too small for replacement teeth")

    axis_start = cq.Vector(center_x, y_min, center_z)
    axis_dir = cq.Vector(0, 1, 0)

    # Remove all original rounded tooth geometry outside the selected root circle.
    root_clipping_cylinder = cq.Solid.makeCylinder(
        root_radius,
        face_width,
        axis_start,
        axis_dir
    )
    retained_body = main_solid.intersect(root_clipping_cylinder)

    # Build the complete 28-tooth perimeter as one continuous planar polygon.
    # This avoids the disconnected solids produced by separately fusing marginally
    # overlapping teeth. Each tooth has straight transverse flanks and a straight
    # chordal crest.
    pitch_angle = 2.0 * math.pi / tooth_count
    root_half_angle = 0.32 * pitch_angle
    tip_half_angle = 0.18 * pitch_angle
    perimeter_vertices = []

    for index in range(tooth_count):
        center_angle = index * pitch_angle
        polar_vertices = (
            (root_radius, center_angle - root_half_angle),
            (outside_radius, center_angle - tip_half_angle),
            (outside_radius, center_angle + tip_half_angle),
            (root_radius, center_angle + root_half_angle)
        )
        for radius, angle in polar_vertices:
            perimeter_vertices.append(
                cq.Vector(
                    center_x + radius * math.cos(angle),
                    y_min,
                    center_z + radius * math.sin(angle)
                )
            )

    outer_wire = cq.Wire.makePolygon(perimeter_vertices, close=True)
    outer_face = cq.Face.makeFromWires(outer_wire)
    gear_disk = cq.Solid.extrudeLinear(
        outer_face,
        cq.Vector(0, face_width, 0)
    )

    # Turn the toothed disk into an annular toothed ring so the original spokes,
    # lightening openings, carrier, and hub geometry remain unchanged.
    inner_cylinder = cq.Solid.makeCylinder(
        ring_inner_radius,
        face_width,
        axis_start,
        axis_dir
    )
    toothed_ring = gear_disk.cut(inner_cylinder)

    # The annular ring overlaps the retained original structural rim and therefore
    # forms one connected main solid after the Boolean union.
    edited_main = retained_body.fuse(toothed_ring)
    try:
        edited_main = edited_main.clean()
    except Exception:
        pass

    edited_main_solids = list(edited_main.Solids())
    if len(edited_main_solids) != 1:
        raise ValueError(
            "Replacement gear body did not merge into one solid; "
            f"Boolean result contains {len(edited_main_solids)} solids"
        )

    edited_main = edited_main_solids[0]
    if not edited_main.isValid():
        raise ValueError("The replacement spur-gear body is not a valid closed solid")

    # Preserve the original splined insert as the second coaxial solid.
    result_solids = [edited_main] + insert_solids
    result_shape = cq.Compound.makeCompound(result_solids)
    result_bb = result_shape.BoundingBox()

    print(f"Original solids: {len(solids)}")
    print(f"Replacement tooth count: {tooth_count}")
    print(f"Root diameter: {2.0 * root_radius:.3f} mm")
    print(f"Outside diameter: {2.0 * outside_radius:.3f} mm")
    print(f"Straight tooth face width: {face_width:.3f} mm")
    print("Tooth profile: straight-sided trapezoidal spur teeth")
    print("Helix angle: 0 degrees")
    print(f"Edited main solid valid: {edited_main.isValid()}")
    print(f"Edited main solid count: {len(edited_main.Solids())}")
    print(f"Result solids: {len(result_shape.Solids())}")
    print(f"Result faces: {len(result_shape.Faces())}")
    print(f"Result volume: {result_shape.Volume():.6f} mm^3")
    print(
        f"Result bbox: x={result_bb.xlen:.4f}, "
        f"y={result_bb.ylen:.4f}, z={result_bb.zlen:.4f} mm"
    )

    return cq.Workplane("XY").newObject([result_shape])