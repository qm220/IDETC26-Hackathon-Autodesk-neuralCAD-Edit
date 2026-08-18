def my_cad_function(args):
    import os
    import math
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    source_shape = imported.val()
    solids = list(source_shape.Solids())

    if len(solids) < 2:
        raise ValueError(f"Expected the original two-solid model, but found {len(solids)} solid(s)")

    # The large solid is the sprocket body; the smaller solid is the splined insert.
    main_solid = max(solids, key=lambda s: s.Volume())
    other_solids = [s for s in solids if s is not main_solid]
    bb = main_solid.BoundingBox()

    # The imported part's rotation axis is parallel to global Y.
    center_x = 0.5 * (bb.xmin + bb.xmax)
    center_z = 0.5 * (bb.zmin + bb.zmax)
    y_min = bb.ymin
    y_max = bb.ymax
    face_width = y_max - y_min
    outside_radius = 0.5 * max(bb.xlen, bb.zlen)

    # Measurements inferred from the existing 113 mm, 28-tooth sprocket envelope.
    tooth_count = 28
    root_radius = 49.55
    ring_inner_radius = 46.80

    if outside_radius <= root_radius:
        raise ValueError("Detected outside radius is too small for the replacement teeth")

    axis_start = cq.Vector(center_x, y_min, center_z)
    axis_dir = cq.Vector(0, 1, 0)

    # Defeature the old rounded chain-sprocket tooth array by retaining only the
    # original body inside the new root circle.
    clipping_cylinder = cq.Solid.makeCylinder(
        root_radius,
        face_width,
        axis_start,
        axis_dir
    )
    retained_body = main_solid.intersect(clipping_cylinder)

    # Rebuild a clean, continuous structural rim. This overlaps the retained
    # spoke/rim junction and provides a reliable base for all new teeth.
    outer_ring_cylinder = cq.Solid.makeCylinder(
        root_radius,
        face_width,
        axis_start,
        axis_dir
    )
    inner_ring_cylinder = cq.Solid.makeCylinder(
        ring_inner_radius,
        face_width,
        axis_start,
        axis_dir
    )
    replacement_ring = outer_ring_cylinder.cut(inner_ring_cylinder)

    edited_main = retained_body.fuse(replacement_ring)

    # Straight-sided transverse tooth profile. Extrusion is parallel to the
    # central axis, so every flank has a straight axial generator and zero
    # helix angle. The crest is a straight chord, with no rounded nose or edge
    # fillets.
    angular_pitch = 2.0 * math.pi / tooth_count
    root_half_angle = 0.32 * angular_pitch
    tip_half_angle = 0.18 * angular_pitch
    tooth_root_overlap = root_radius - 0.65

    for index in range(tooth_count):
        angle = index * angular_pitch
        polar_points = [
            (tooth_root_overlap, angle - root_half_angle),
            (outside_radius, angle - tip_half_angle),
            (outside_radius, angle + tip_half_angle),
            (tooth_root_overlap, angle + root_half_angle)
        ]

        vertices = [
            cq.Vector(
                center_x + radius * math.cos(theta),
                y_min,
                center_z + radius * math.sin(theta)
            )
            for radius, theta in polar_points
        ]

        tooth_wire = cq.Wire.makePolygon(vertices, close=True)
        tooth_face = cq.Face.makeFromWires(tooth_wire)
        tooth_solid = cq.Solid.extrudeLinear(
            tooth_face,
            cq.Vector(0, face_width, 0)
        )
        edited_main = edited_main.fuse(tooth_solid)

    # Heal coincident boundaries created by the repeated Boolean unions.
    try:
        edited_main = edited_main.clean()
    except Exception:
        pass

    if not edited_main.isValid():
        raise ValueError("The replacement spur-gear body is not a valid closed solid")

    # Keep the original splined hub insert as a separate coaxial solid.
    result_solids = [edited_main] + other_solids
    result_shape = cq.Compound.makeCompound(result_solids)

    result_bb = result_shape.BoundingBox()
    print(f"Original solids: {len(solids)}")
    print(f"Replacement tooth count: {tooth_count}")
    print(f"Root diameter: {2.0 * root_radius:.3f} mm")
    print(f"Outside diameter: {2.0 * outside_radius:.3f} mm")
    print(f"Straight tooth face width: {face_width:.3f} mm")
    print("Helix angle: 0 degrees")
    print(f"Edited main solid valid: {edited_main.isValid()}")
    print(f"Result solids: {len(result_shape.Solids())}")
    print(f"Result faces: {len(result_shape.Faces())}")
    print(f"Result volume: {result_shape.Volume():.6f} mm^3")
    print(
        f"Result bbox: x={result_bb.xlen:.4f}, "
        f"y={result_bb.ylen:.4f}, z={result_bb.zlen:.4f} mm"
    )

    return cq.Workplane("XY").newObject([result_shape])