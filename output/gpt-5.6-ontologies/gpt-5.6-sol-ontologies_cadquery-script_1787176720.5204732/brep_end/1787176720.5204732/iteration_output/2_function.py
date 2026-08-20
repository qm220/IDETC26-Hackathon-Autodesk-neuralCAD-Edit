def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    source = imported.val()
    solids = list(source.Solids())

    if len(solids) < 3:
        raise ValueError(f"Expected at least three source solids, found {len(solids)}")

    def max_span(s):
        b = s.BoundingBox()
        return max(b.xlen, b.ylen, b.zlen)

    # Preserve the two longest structural blades and the compact clamp.
    ordered = sorted(solids, key=max_span, reverse=True)
    blade_a = ordered[0]
    blade_b = ordered[1]
    clamp = ordered[-1]

    # Rigidly copy the diagonal blade. This preserves its end bores, root
    # transitions, section profile, and the radii on all four long edges.
    third_blade = blade_a.rotate(
        cq.Vector(0, 0, 0),
        cq.Vector(0, 1, 0),
        66.98
    )

    # Locate the stack plane from the compact clamp instead of relying on a
    # hard-coded global Y coordinate.
    cb = clamp.BoundingBox()
    stack_center_y = (cb.ymin + cb.ymax) / 2.0

    central_thickness = 0.42
    clearance = 0.03
    layer_pitch = central_thickness + clearance

    y_a = stack_center_y - layer_pitch
    y_new = stack_center_y
    y_b = stack_center_y + layer_pitch

    # Use overlapping inner/outer central zones. The overlap avoids the
    # tangent-only joins that fragmented the blades in the previous result.
    cut_radius = 40.0
    insert_radius = 46.0

    cut_zone = cq.Solid.makeCylinder(
        cut_radius,
        200.0,
        cq.Vector(0, stack_center_y - 100.0, 0),
        cq.Vector(0, 1, 0)
    )
    insert_zone = cq.Solid.makeCylinder(
        insert_radius,
        200.0,
        cq.Vector(0, stack_center_y - 100.0, 0),
        cq.Vector(0, 1, 0)
    )

    def slab(y_mid):
        return cq.Solid.makeBox(
            1000.0,
            central_thickness,
            1000.0,
            cq.Vector(-500.0, y_mid - central_thickness / 2.0, -500.0)
        )

    def y_center(shape):
        b = shape.BoundingBox()
        return (b.ymin + b.ymax) / 2.0

    def make_thin_centered_blade(full_blade, target_y):
        # Keep all noncentral geometry exactly as imported.
        outer = full_blade.cut(cut_zone)

        # Shift only a copy used to construct the central insert. Intersecting
        # it with a 0.42 mm slab gives the requested central thickness while
        # preserving the blade's planform and radiused longitudinal edges.
        dy = target_y - y_center(full_blade)
        shifted = full_blade.translate(cq.Vector(0, dy, 0))
        center_insert = shifted.intersect(insert_zone).intersect(slab(target_y))

        if center_insert.isNull():
            raise ValueError("Failed to construct a central blade insert")

        return outer.fuse(center_insert)

    edited_a = make_thin_centered_blade(blade_a, y_a)
    edited_new = make_thin_centered_blade(third_blade, y_new)
    edited_b = make_thin_centered_blade(blade_b, y_b)

    # Keep the assembly members as separate components rather than merging
    # intersecting blades or the clamp into a single boolean solid.
    final_shape = cq.Compound.makeCompound([
        edited_a,
        edited_new,
        edited_b,
        clamp
    ])

    print("=== THREE-BLADE ROTOR EDIT, CONNECTIVITY REVISION ===")
    print(f"Source solids: {len(solids)}")
    print("Final rotor blade count: 3")
    print(f"Stack center Y: {stack_center_y:.3f} mm")
    print(f"Central thickness: {central_thickness:.3f} mm")
    print(f"Central layer Y positions: {y_a:.3f}, {y_new:.3f}, {y_b:.3f} mm")
    print("Added blade is a rigid copy of an existing radiused blade")
    print(f"Edited blade solid counts: {len(edited_a.Solids())}, {len(edited_new.Solids())}, {len(edited_b.Solids())}")
    print(f"Result solids: {len(final_shape.Solids())}")
    print(f"Result valid: {final_shape.isValid()}")

    return cq.Workplane("XY").newObject([final_shape])