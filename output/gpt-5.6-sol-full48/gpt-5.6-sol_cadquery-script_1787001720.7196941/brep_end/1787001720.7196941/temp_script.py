def my_cad_function(args):
    import os
    import math
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    solids = list(imported.val().Solids())

    if len(solids) < 2:
        raise ValueError(f"Expected at least two source solids, found {len(solids)}")

    # The large-volume solid is the sprocket body; all other solids are preserved.
    main_solid = max(solids, key=lambda s: s.Volume())
    insert_solids = [s for s in solids if not s.isSame(main_solid)]
    if not insert_solids:
        # Fallback for CadQuery builds where isSame is unavailable or overly broad.
        ordered = sorted(solids, key=lambda s: s.Volume(), reverse=True)
        main_solid = ordered[0]
        insert_solids = ordered[1:]

    bb = main_solid.BoundingBox()
    dimensions = {"X": bb.xlen, "Y": bb.ylen, "Z": bb.zlen}

    # Detect the axial direction from the shortest bounding-box dimension instead
    # of assuming a fixed STEP orientation.
    axial_name = min(dimensions, key=dimensions.get)
    if axial_name == "X":
        axial_min, axial_max = bb.xmin, bb.xmax
        axis_dir = cq.Vector(1, 0, 0)
        radial_u = cq.Vector(0, 1, 0)
        radial_v = cq.Vector(0, 0, 1)
        axis_center = cq.Vector(
            axial_min,
            0.5 * (bb.ymin + bb.ymax),
            0.5 * (bb.zmin + bb.zmax)
        )
        radial_lengths = (bb.ylen, bb.zlen)
    elif axial_name == "Y":
        axial_min, axial_max = bb.ymin, bb.ymax
        axis_dir = cq.Vector(0, 1, 0)
        radial_u = cq.Vector(1, 0, 0)
        radial_v = cq.Vector(0, 0, 1)
        axis_center = cq.Vector(
            0.5 * (bb.xmin + bb.xmax),
            axial_min,
            0.5 * (bb.zmin + bb.zmax)
        )
        radial_lengths = (bb.xlen, bb.zlen)
    else:
        axial_min, axial_max = bb.zmin, bb.zmax
        axis_dir = cq.Vector(0, 0, 1)
        radial_u = cq.Vector(1, 0, 0)
        radial_v = cq.Vector(0, 1, 0)
        axis_center = cq.Vector(
            0.5 * (bb.xmin + bb.xmax),
            0.5 * (bb.ymin + bb.ymax),
            axial_min
        )
        radial_lengths = (bb.xlen, bb.ylen)

    face_width = axial_max - axial_min
    outside_radius = 0.5 * max(radial_lengths)

    if face_width <= 0 or outside_radius <= 0:
        raise ValueError("Invalid source-model bounding box")

    # Retain the observed 28-position circumferential pattern and the original
    # outside envelope. The root ratio corresponds to the measured source rim.
    tooth_count = 28
    root_radius = 0.8770 * outside_radius
    ring_inner_radius = root_radius - 3.25

    if ring_inner_radius <= 0 or root_radius >= outside_radius:
        raise ValueError("Invalid derived spur-gear radii")

    # Use an oversized axial clipping cylinder to avoid coincident end-face
    # Boolean failures while removing the original rounded external teeth.
    axial_margin = max(0.5, 0.08 * face_width)
    clip_start = axis_center - axis_dir.multiply(axial_margin)
    root_clip = cq.Solid.makeCylinder(
        root_radius,
        face_width + 2.0 * axial_margin,
        clip_start,
        axis_dir
    )
    retained_body = main_solid.intersect(root_clip)

    retained_components = list(retained_body.Solids())
    if not retained_components:
        raise ValueError("Root clipping removed the complete sprocket body")

    # Construct a continuous straight-sided transverse spur profile. Every tooth
    # has planar flanks and a straight chordal crest; extrusion is untwisted and
    # parallel to the detected gear axis.
    pitch_angle = 2.0 * math.pi / tooth_count
    root_half_angle = 0.34 * pitch_angle
    tip_half_angle = 0.17 * pitch_angle
    perimeter_points = []

    for index in range(tooth_count):
        angle = index * pitch_angle
        tooth_points = (
            (root_radius, angle - root_half_angle),
            (outside_radius, angle - tip_half_angle),
            (outside_radius, angle + tip_half_angle),
            (root_radius, angle + root_half_angle)
        )
        for radius, theta in tooth_points:
            point = (
                axis_center
                + radial_u.multiply(radius * math.cos(theta))
                + radial_v.multiply(radius * math.sin(theta))
            )
            perimeter_points.append(point)

    outer_wire = cq.Wire.makePolygon(perimeter_points, close=True)
    outer_face = cq.Face.makeFromWires(outer_wire)
    toothed_disk = cq.Solid.extrudeLinear(
        outer_face,
        axis_dir.multiply(face_width)
    )

    inner_cut = cq.Solid.makeCylinder(
        ring_inner_radius,
        face_width + 2.0 * axial_margin,
        clip_start,
        axis_dir
    )
    toothed_ring = toothed_disk.cut(inner_cut)

    # Fuse the replacement ring to each retained component. The generous radial
    # overlap reaches into the original structural rim and avoids tangent-only
    # contact at the old tooth-root boundary.
    edited_shape = retained_body.fuse(toothed_ring)
    try:
        edited_shape = edited_shape.clean()
    except Exception:
        pass

    edited_solids = list(edited_shape.Solids())
    if len(edited_solids) != 1:
        # Retry with an annular bridge extending farther inward. This remains in
        # the outer structural-rim zone and guarantees volumetric union without
        # modifying the hub, spline, or main spoke openings.
        bridge_inner_radius = max(0.0, ring_inner_radius - 1.25)
        bridge_outer = cq.Solid.makeCylinder(
            root_radius + 0.75,
            face_width,
            axis_center,
            axis_dir
        )
        bridge_inner = cq.Solid.makeCylinder(
            bridge_inner_radius,
            face_width + 2.0 * axial_margin,
            clip_start,
            axis_dir
        )
        bridge = bridge_outer.cut(bridge_inner)
        edited_shape = retained_body.fuse(bridge).fuse(toothed_ring)
        try:
            edited_shape = edited_shape.clean()
        except Exception:
            pass
        edited_solids = list(edited_shape.Solids())

    if len(edited_solids) != 1:
        volumes = [round(s.Volume(), 3) for s in edited_solids]
        raise ValueError(
            f"Edited sprocket is not one connected solid: {len(edited_solids)} "
            f"components with volumes {volumes}"
        )

    edited_main = edited_solids[0]
    if not edited_main.isValid():
        raise ValueError("The edited spur-gear sprocket is not a valid solid")

    result_shape = cq.Compound.makeCompound([edited_main] + insert_solids)
    result_bb = result_shape.BoundingBox()

    print(f"Detected axial direction: {axial_name}")
    print(f"Original solid count: {len(solids)}")
    print(f"Retained components after clipping: {len(retained_components)}")
    print(f"Replacement tooth count: {tooth_count}")
    print(f"Outside diameter: {2.0 * outside_radius:.3f} mm")
    print(f"Root diameter: {2.0 * root_radius:.3f} mm")
    print(f"Axial tooth width: {face_width:.3f} mm")
    print("Tooth form: straight-sided trapezoidal spur teeth")
    print("Helix angle: 0 degrees")
    print(f"Edited main solid valid: {edited_main.isValid()}")
    print(f"Final solid count: {len(result_shape.Solids())}")
    print(f"Final face count: {len(result_shape.Faces())}")
    print(f"Final volume: {result_shape.Volume():.6f} mm^3")
    print(
        f"Final bbox: x={result_bb.xlen:.4f}, "
        f"y={result_bb.ylen:.4f}, z={result_bb.zlen:.4f} mm"
    )

    return cq.Workplane("XY").newObject([result_shape])