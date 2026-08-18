def my_cad_function(args):
    import os
    import math

    input_file = os.path.expanduser(args['input_file'])
    base = cq.importers.importStep(input_file)
    base_shape = base.val()
    bbox = base_shape.BoundingBox()

    xmin, xmax = bbox.xmin, bbox.xmax
    ymin, ymax = bbox.ymin, bbox.ymax
    zmin, zmax = bbox.zmin, bbox.zmax
    print('Base valid:', base_shape.isValid())
    print('Base volume:', base_shape.Volume())
    print('Base faces:', len(base_shape.Faces()))
    print('Bounding box: x=(%.3f, %.3f), y=(%.3f, %.3f), z=(%.3f, %.3f)' %
          (xmin, xmax, ymin, ymax, zmin, zmax))

    # The positive-X end is the hook. Sample the adjacent narrow arm region to
    # derive a hinge position and the local width from the actual imported model.
    overall_length = xmax - xmin
    hinge_x = xmax - min(18.0, 0.14 * overall_length)
    sampling_slab = cq.Workplane('XY').box(
        2.0, (ymax - ymin) + 20.0, (zmax - zmin) + 20.0
    ).translate((hinge_x, 0, 0.5 * (zmin + zmax)))

    local_shape = base.intersect(sampling_slab).val()
    if local_shape.isNull() or local_shape.Volume() < 0.01:
        hinge_x = xmax - min(22.0, 0.18 * overall_length)
        sampling_slab = cq.Workplane('XY').box(
            3.0, (ymax - ymin) + 20.0, (zmax - zmin) + 20.0
        ).translate((hinge_x, 0, 0.5 * (zmin + zmax)))
        local_shape = base.intersect(sampling_slab).val()

    local_box = local_shape.BoundingBox()
    local_half_width = max(abs(local_box.ymin), abs(local_box.ymax))
    local_depth = local_box.zmax - local_box.zmin
    hinge_z = local_box.zmax - 5.0
    if hinge_z < local_box.zmin + 4.5:
        hinge_z = 0.5 * (local_box.zmin + local_box.zmax)

    print('Derived hinge axis: (x=%.3f, z=%.3f), axis parallel to Y' %
          (hinge_x, hinge_z))
    print('Local arm width %.3f and depth %.3f' %
          (2.0 * local_half_width, local_depth))

    # Add the nominal 3 mm transverse hinge bore to the existing lever.
    pin_diameter = 3.0
    base_bore_diameter = 3.20
    bore_length = (ymax - ymin) + 16.0
    bore = cq.Workplane(obj=cq.Solid.makeCylinder(
        base_bore_diameter / 2.0,
        bore_length,
        cq.Vector(hinge_x, -0.5 * bore_length, hinge_z),
        cq.Vector(0, 1, 0)
    ))
    modified_base = base.cut(bore)

    # Place two external gate cheeks beyond the maximum local hook/arm width.
    # The cheeks are separate moving components with 0.25 mm side clearance.
    side_clearance = 0.25
    cheek_thickness = 2.0
    cheek_inner_y = local_half_width + side_clearance
    bridge_radius = 2.15

    # Search the upper hook-throat region for a transverse bridge position that
    # does not intersect the protected hook body. This uses the imported solid,
    # rather than relying solely on nominal coordinates.
    bridge_y0 = -(cheek_inner_y + cheek_thickness)
    bridge_length = 2.0 * (cheek_inner_y + cheek_thickness)
    best = None
    hook_height = zmax - zmin
    x_offsets = [3.0, 4.0, 5.0, 6.0, 7.5, 9.0, 11.0, 13.0]
    z_offsets = [3.0, 4.5, 6.0, 7.5, 9.0, 11.0, 13.0]
    for xo in x_offsets:
        for zo in z_offsets:
            tx = xmax - xo
            tz = zmax - zo
            if tx <= hinge_x + 6.0:
                continue
            trial = cq.Solid.makeCylinder(
                bridge_radius,
                bridge_length,
                cq.Vector(tx, bridge_y0, tz),
                cq.Vector(0, 1, 0)
            )
            try:
                collision_volume = trial.intersect(base_shape).Volume()
            except Exception:
                collision_volume = 1.0e9
            if collision_volume < 0.02:
                # Favor a position near the terminal nose, but slightly below
                # the exposed top so the bridge closes the throat rather than
                # resting on the nose cap.
                score = tx + 0.12 * tz
                if best is None or score > best[0]:
                    best = (score, tx, tz)

    if best is None:
        gate_tip_x = xmax - 8.0
        gate_tip_z = zmax - 7.0
        print('Warning: no collision-free throat sample found; using fallback gate tip')
    else:
        gate_tip_x, gate_tip_z = best[1], best[2]

    print('Gate bridge center: (x=%.3f, z=%.3f)' %
          (gate_tip_x, gate_tip_z))

    dx = gate_tip_x - hinge_x
    dz = gate_tip_z - hinge_z
    gate_length = math.sqrt(dx * dx + dz * dz)
    gate_angle = math.degrees(math.atan2(dz, dx))
    hub_radius = 5.0
    arm_depth = 3.6
    tip_radius = bridge_radius + 0.35

    def make_cheek(y_start):
        hub = cq.Workplane(obj=cq.Solid.makeCylinder(
            hub_radius,
            cheek_thickness,
            cq.Vector(hinge_x, y_start, hinge_z),
            cq.Vector(0, 1, 0)
        ))
        tip = cq.Workplane(obj=cq.Solid.makeCylinder(
            tip_radius,
            cheek_thickness,
            cq.Vector(gate_tip_x, y_start, gate_tip_z),
            cq.Vector(0, 1, 0)
        ))
        arm = (
            cq.Workplane('XY')
            .box(gate_length, cheek_thickness, arm_depth)
            .rotate((0, 0, 0), (0, 1, 0), -gate_angle)
            .translate((0.5 * (hinge_x + gate_tip_x),
                        y_start + 0.5 * cheek_thickness,
                        0.5 * (hinge_z + gate_tip_z)))
        )
        cheek = hub.union(arm).union(tip)
        gate_bore = cq.Workplane(obj=cq.Solid.makeCylinder(
            1.65,
            cheek_thickness + 1.0,
            cq.Vector(hinge_x, y_start - 0.5, hinge_z),
            cq.Vector(0, 1, 0)
        ))
        return cheek.cut(gate_bore)

    negative_cheek = make_cheek(-cheek_inner_y - cheek_thickness)
    positive_cheek = make_cheek(cheek_inner_y)

    # The transverse rounded bridge closes the hook throat across the complete
    # width. It joins both cheeks and supplies a snag-resistant insertion face.
    bridge = cq.Workplane(obj=cq.Solid.makeCylinder(
        bridge_radius,
        bridge_length,
        cq.Vector(gate_tip_x, bridge_y0, gate_tip_z),
        cq.Vector(0, 1, 0)
    ))
    gate = negative_cheek.union(positive_cheek).union(bridge)

    # Transverse hinge pin with symmetric retaining heads.
    spring_extra = 3.2
    pin_y0 = -cheek_inner_y - cheek_thickness - spring_extra
    pin_length = 2.0 * (cheek_inner_y + cheek_thickness + spring_extra)
    pin = cq.Workplane(obj=cq.Solid.makeCylinder(
        pin_diameter / 2.0,
        pin_length,
        cq.Vector(hinge_x, pin_y0, hinge_z),
        cq.Vector(0, 1, 0)
    ))
    head_radius = 2.45
    head_thickness = 0.8
    head_a = cq.Workplane(obj=cq.Solid.makeCylinder(
        head_radius, head_thickness,
        cq.Vector(hinge_x, pin_y0 - head_thickness, hinge_z),
        cq.Vector(0, 1, 0)
    ))
    head_b = cq.Workplane(obj=cq.Solid.makeCylinder(
        head_radius, head_thickness,
        cq.Vector(hinge_x, pin_y0 + pin_length, hinge_z),
        cq.Vector(0, 1, 0)
    ))
    pin = pin.union(head_a).union(head_b)

    # Simplified torsion return spring: three narrow annular coils around the
    # pin outside the positive gate cheek, plus a tangential reaction leg.
    spring_parts = []
    spring_inner_radius = 1.75
    spring_outer_radius = 2.55
    coil_width = 0.42
    spring_y = cheek_inner_y + cheek_thickness + 0.35
    for i in range(3):
        yy = spring_y + i * 0.55
        outer = cq.Workplane(obj=cq.Solid.makeCylinder(
            spring_outer_radius, coil_width,
            cq.Vector(hinge_x, yy, hinge_z), cq.Vector(0, 1, 0)
        ))
        inner = cq.Workplane(obj=cq.Solid.makeCylinder(
            spring_inner_radius, coil_width + 0.2,
            cq.Vector(hinge_x, yy - 0.1, hinge_z), cq.Vector(0, 1, 0)
        ))
        spring_parts.append(outer.cut(inner))
    spring = spring_parts[0].union(spring_parts[1]).union(spring_parts[2])

    leg_length = 7.0
    leg = (
        cq.Workplane('XY')
        .box(leg_length, 0.7, 0.7)
        .rotate((0, 0, 0), (0, 1, 0), -25.0)
        .translate((hinge_x + 0.5 * leg_length,
                    spring_y + 0.55,
                    hinge_z + 0.8))
    )
    spring = spring.union(leg)

    assembly = cq.Assembly(name='lever_with_safety_gate')
    assembly.add(modified_base, name='modified_lever',
                 color=cq.Color(0.72, 0.72, 0.76))
    assembly.add(gate, name='pivoting_safety_gate',
                 color=cq.Color(0.92, 0.55, 0.12))
    assembly.add(pin, name='hinge_pin',
                 color=cq.Color(0.30, 0.32, 0.35))
    assembly.add(spring, name='torsion_return_spring',
                 color=cq.Color(0.82, 0.82, 0.28))

    print('Created normally-closed forked safety gate, hinge pin, and return spring.')
    print('Gate length %.3f mm, gate angle %.3f degrees' %
          (gate_length, gate_angle))
    return assembly