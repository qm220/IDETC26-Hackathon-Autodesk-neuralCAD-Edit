def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    source = imported.val()
    solids = list(source.Solids())

    if len(solids) < 3:
        raise ValueError(f"Expected at least three source solids, found {len(solids)}")

    # Identify the two long rotor blades and the compact clamp assembly by span.
    def max_span(s):
        b = s.BoundingBox()
        return max(b.xlen, b.ylen, b.zlen)

    ordered = sorted(solids, key=max_span, reverse=True)
    blade_a = ordered[0]
    blade_b = ordered[1]
    clamp = ordered[-1]

    # The diagonal source blade is copied and mirrored angularly about the stack
    # axis. Its original axis is approximately +33.49 degrees in the XZ plane;
    # this rotation places the copy at approximately -33.49 degrees, producing
    # three near-equally spaced diametric rotor blades with the vertical blade.
    third_blade_full = blade_a.rotate(
        cq.Vector(0, 0, 0), cq.Vector(0, 1, 0), 66.98
    )

    # Existing long-edge radii are inherited exactly from blade_a by the rigid
    # copy, including its four radiused longitudinal edges and end details.

    # Central adjustment parameters in millimetres.
    center_y = 6.35
    central_thickness = 0.42
    layer_gap = 0.10
    central_radius = 43.20

    # This cylinder bounds the existing root-transition/central region while
    # leaving the non-targeted outer blade geometry unchanged.
    central_zone = cq.Solid.makeCylinder(
        central_radius,
        100.0,
        cq.Vector(0, -50.0, 0),
        cq.Vector(0, 1, 0),
    )

    def slab(y_mid):
        return cq.Solid.makeBox(
            1000.0,
            central_thickness,
            1000.0,
            cq.Vector(-500.0, y_mid - central_thickness / 2.0, -500.0),
        )

    # Put the new blade directly through the center of the stack. The two
    # existing blade centers occupy adjacent 0.42 mm layers.
    pitch = central_thickness + layer_gap
    y_a = center_y - pitch
    y_new = center_y
    y_b = center_y + pitch

    def thin_central_portion(full_blade, y_mid):
        outer = full_blade.cut(central_zone)
        center_profile = full_blade.intersect(central_zone)
        thin_center = center_profile.intersect(slab(y_mid))
        result = outer.fuse(thin_center)
        return result

    edited_a = thin_central_portion(blade_a, y_a)
    edited_b = thin_central_portion(blade_b, y_b)
    edited_new = thin_central_portion(third_blade_full, y_new)

    # Preserve the clamp as an independent assembly component and avoid
    # combining intersecting assembly members into one boolean solid.
    final_shape = cq.Compound.makeCompound([
        edited_a,
        edited_b,
        edited_new,
        clamp,
    ])

    print("=== THREE-BLADE ROTOR EDIT ===")
    print(f"Source solids: {len(solids)}")
    print("Rotor blades in result: 3")
    print(f"Central thickness per blade: {central_thickness:.3f} mm")
    print(f"Central layer Y positions: {y_a:.3f}, {y_new:.3f}, {y_b:.3f} mm")
    print("Third blade copied from diagonal source and rotated 66.98 degrees about Y")
    print(f"Result valid: {final_shape.isValid()}")
    print(f"Result solids: {len(final_shape.Solids())}")

    return cq.Workplane("XY").newObject([final_shape])