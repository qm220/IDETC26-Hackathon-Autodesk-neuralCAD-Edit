def my_cad_function(args):
    import cadquery as cq

    imported = cq.importers.importStep(args["input_file"])
    source_shape = imported.val()
    source_solids = list(source_shape.Solids())

    if not source_solids:
        raise ValueError("The input STEP file contains no solids")

    # Separate the two long rotor members from the compact hub assembly.
    blade_solids = []
    preserved_solids = []
    for solid in source_solids:
        bb = solid.BoundingBox()
        if max(bb.xlen, bb.zlen) > 80.0:
            blade_solids.append(solid)
        else:
            preserved_solids.append(solid)

    if len(blade_solids) < 2:
        raise ValueError("Could not identify both original rotor blades")

    # Select the substantially Z-aligned member as the exact template for the
    # third blade. This preserves its length, rounded longitudinal geometry,
    # end profiles, axial bores, pivot bore, and local attachment details.
    template = max(blade_solids, key=lambda s: s.BoundingBox().zlen)

    central_thickness = 0.42
    inner_radius = 14.0
    transition_radius = 22.0

    def make_transition_envelope(y_center, full_half_thickness):
        # Axisymmetric envelope about the Y stack axis. It holds the inner
        # overlap region at 0.42 mm and ramps smoothly to the original blade
        # thickness before reaching the unmodified outer arm.
        thin_half = central_thickness / 2.0
        full_half = max(full_half_thickness, thin_half + 0.05)
        profile = (
            cq.Workplane("XY")
            .moveTo(0.0, y_center - thin_half)
            .lineTo(inner_radius, y_center - thin_half)
            .lineTo(transition_radius, y_center - full_half)
            .lineTo(transition_radius, y_center + full_half)
            .lineTo(inner_radius, y_center + thin_half)
            .lineTo(0.0, y_center + thin_half)
            .close()
        )
        return profile.revolve(
            360.0,
            axisStart=(0.0, y_center - full_half - 1.0),
            axisEnd=(0.0, y_center + full_half + 1.0)
        ).val()

    edit_cylinder = cq.Solid.makeCylinder(
        transition_radius,
        200.0,
        cq.Vector(0.0, -100.0, 0.0),
        cq.Vector(0.0, 1.0, 0.0)
    )

    def thin_central_portion(blade):
        bb = blade.BoundingBox()
        y_center = 0.5 * (bb.ymin + bb.ymax)
        half_thickness = 0.5 * bb.ylen
        envelope = make_transition_envelope(y_center, half_thickness)

        unchanged_outer = blade.cut(edit_cylinder)
        transitioned_center = blade.intersect(edit_cylinder).intersect(envelope)

        try:
            return unchanged_outer.fuse(transitioned_center)
        except Exception:
            return cq.Compound.makeCompound([unchanged_outer, transitioned_center])

    # Thin the central overlap region of both existing blades while leaving all
    # remote arm and end-interface geometry unchanged.
    modified_existing = [thin_central_portion(blade) for blade in blade_solids[:2]]

    # Put the duplicated member through the middle of the existing stack.
    blade_centers_y = [
        0.5 * (b.BoundingBox().ymin + b.BoundingBox().ymax)
        for b in blade_solids[:2]
    ]
    stack_mid_y = sum(blade_centers_y) / len(blade_centers_y)
    template_y = 0.5 * (template.BoundingBox().ymin + template.BoundingBox().ymax)

    new_blade = template.translate(cq.Vector(0.0, stack_mid_y - template_y, 0.0))

    # The original oblique blade lies approximately +60 degrees from the
    # Z-aligned member. Rotate the duplicate in the opposite direction so the
    # final plan view has three distinct centerlines and six radial arms.
    new_blade = new_blade.rotate(
        cq.Vector(0.0, 0.0, 0.0),
        cq.Vector(0.0, 1.0, 0.0),
        -60.0
    )
    new_blade = thin_central_portion(new_blade)

    # Preserve any unexpected additional long solids without alteration.
    extras = blade_solids[2:]
    result_shapes = preserved_solids + modified_existing + extras + [new_blade]
    result = cq.Compound.makeCompound(result_shapes)

    print("Original solids:", len(source_solids))
    print("Existing blades locally reduced to 0.42 mm:", len(modified_existing))
    print("Added exact-design duplicate at -60 degrees through stack midpoint")
    return cq.Workplane("XY").newObject([result])