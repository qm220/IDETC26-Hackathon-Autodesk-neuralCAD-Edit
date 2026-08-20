def my_cad_function(args):
    import cadquery as cq

    # Load the original assembly and retain its exact hub and outer-blade geometry.
    imported = cq.importers.importStep(args["input_file"])
    source_shape = imported.val()
    source_solids = list(source_shape.Solids())

    if not source_solids:
        raise ValueError("The input STEP file contains no solids")

    # The original model contains two very long blade solids and a compact hub.
    blade_solids = []
    preserved_solids = []
    for solid in source_solids:
        bb = solid.BoundingBox()
        radial_span = max(bb.xlen, bb.zlen)
        if radial_span > 80.0:
            blade_solids.append(solid)
        else:
            preserved_solids.append(solid)

    if len(blade_solids) < 2:
        raise ValueError("Could not identify both original rotor-blade members")

    # Cylindrical editing region centered on the fixed Y-axis. Only geometry
    # inside this region is thinned; the remote arms and their end details stay exact.
    transition_radius = 21.0
    edit_cylinder = cq.Solid.makeCylinder(
        transition_radius,
        100.0,
        cq.Vector(0.0, -50.0, 0.0),
        cq.Vector(0.0, 1.0, 0.0)
    )

    central_thickness = 0.42
    modified_blades = []

    for blade in blade_solids[:2]:
        bb = blade.BoundingBox()
        original_y_center = 0.5 * (bb.ymin + bb.ymax)

        thin_slab = cq.Solid.makeBox(
            500.0,
            central_thickness,
            500.0,
            cq.Vector(-250.0, original_y_center - central_thickness / 2.0, -250.0)
        )

        unchanged_outer = blade.cut(edit_cylinder)
        thinned_center = blade.intersect(edit_cylinder).intersect(thin_slab)

        try:
            modified = unchanged_outer.fuse(thinned_center)
        except Exception:
            modified = cq.Compound.makeCompound([unchanged_outer, thinned_center])
        modified_blades.append(modified)

    # Preserve any additional long solids, should the source file contain them.
    for extra_blade in blade_solids[2:]:
        preserved_solids.append(extra_blade)

    # Construct the third double-ended blade. Dimensions follow the established
    # 12.7 mm wide blade design and its approximately 3.175 mm full thickness.
    blade_length = 210.0
    blade_width = 12.7
    full_thickness = 3.175
    longitudinal_edge_radius = 1.20

    new_blade_wp = (
        cq.Workplane("XZ")
        .rect(blade_width, blade_length)
        .extrude(full_thickness / 2.0, both=True)
    )

    # Round all four edges running along the blade length.
    try:
        new_blade_wp = new_blade_wp.edges("|Z").fillet(longitudinal_edge_radius)
    except Exception:
        # A slightly smaller fallback protects against kernel tolerance differences.
        new_blade_wp = new_blade_wp.edges("|Z").fillet(0.9)

    new_blade = new_blade_wp.val()

    # Match the existing remote axial bore/groove interfaces at both ends.
    bore_radius = 3.175
    bore_depth = 55.0
    positive_bore = cq.Solid.makeCylinder(
        bore_radius,
        bore_depth,
        cq.Vector(0.0, 0.0, blade_length / 2.0 - bore_depth),
        cq.Vector(0.0, 0.0, 1.0)
    )
    negative_bore = cq.Solid.makeCylinder(
        bore_radius,
        bore_depth,
        cq.Vector(0.0, 0.0, -blade_length / 2.0 + bore_depth),
        cq.Vector(0.0, 0.0, -1.0)
    )
    new_blade = new_blade.cut(positive_bore).cut(negative_bore)

    # Thin only the central overlap portion of the new blade to 0.42 mm.
    new_center_slab = cq.Solid.makeBox(
        500.0,
        central_thickness,
        500.0,
        cq.Vector(-250.0, -central_thickness / 2.0, -250.0)
    )
    new_outer = new_blade.cut(edit_cylinder)
    new_center = new_blade.intersect(edit_cylinder).intersect(new_center_slab)
    try:
        new_blade = new_outer.fuse(new_center)
    except Exception:
        new_blade = cq.Compound.makeCompound([new_outer, new_center])

    # Preserve the common hub axle by adding the same central pivot clearance.
    pivot_radius = 6.477
    pivot_bore = cq.Solid.makeCylinder(
        pivot_radius,
        100.0,
        cq.Vector(0.0, -50.0, 0.0),
        cq.Vector(0.0, 1.0, 0.0)
    )
    new_blade = new_blade.cut(pivot_bore)

    # Existing blade centerlines are separated by about 60 degrees. The missing
    # symmetric orientation is obtained by rotating the new Z-aligned member 60
    # degrees about the unchanged Y hub axis, yielding six radial arms.
    new_blade = new_blade.rotate(
        cq.Vector(0.0, 0.0, 0.0),
        cq.Vector(0.0, 1.0, 0.0),
        60.0
    )

    result_shapes = preserved_solids + modified_blades + [new_blade]
    result = cq.Compound.makeCompound(result_shapes)

    print("Original solids:", len(source_solids))
    print("Modified existing blades:", len(modified_blades))
    print("Added third blade at 60 degrees with 0.42 mm central thickness")
    return cq.Workplane("XY").newObject([result])