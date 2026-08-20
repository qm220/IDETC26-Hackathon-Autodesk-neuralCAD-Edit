def my_cad_function(args):
    import os
    import math

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    original = imported.val()
    bbox = original.BoundingBox()

    x_max = bbox.xmax
    y_mid = (bbox.ymin + bbox.ymax) * 0.5
    z_max = bbox.zmax

    hinge_x = x_max - 14.0
    hinge_z = z_max - 3.8
    latch_x = x_max - 5.4
    latch_z = z_max - 2.8

    gate_width = 2.4
    gate_thickness = 1.65
    side_clearance = 0.30
    ear_inner_y = gate_width * 0.5 + side_clearance
    ear_outer_y = 4.6

    hinge_ear_r = 3.0
    hinge_boss_r = 2.15
    hinge_pin_r = 1.0
    hinge_bore_r = 1.10

    latch_ear_r = 2.55
    latch_boss_r = 1.65
    latch_pin_r = 0.80
    latch_bore_r = 0.92

    def y_cylinder(radius, y0, y1, x, z):
        solid = cq.Solid.makeCylinder(
            radius,
            y1 - y0,
            cq.Vector(x, y0, z),
            cq.Vector(0, 1, 0)
        )
        return cq.Workplane(obj=solid)

    hinge_ear_neg = y_cylinder(
        hinge_ear_r, y_mid - ear_outer_y, y_mid - ear_inner_y,
        hinge_x, hinge_z
    )
    hinge_ear_pos = y_cylinder(
        hinge_ear_r, y_mid + ear_inner_y, y_mid + ear_outer_y,
        hinge_x, hinge_z
    )
    latch_ear_neg = y_cylinder(
        latch_ear_r, y_mid - ear_outer_y, y_mid - ear_inner_y,
        latch_x, latch_z
    )
    latch_ear_pos = y_cylinder(
        latch_ear_r, y_mid + ear_inner_y, y_mid + ear_outer_y,
        latch_x, latch_z
    )

    body = (
        cq.Workplane(obj=original)
        .union(hinge_ear_neg)
        .union(hinge_ear_pos)
        .union(latch_ear_neg)
        .union(latch_ear_pos)
    )

    bore_y0 = y_mid - ear_outer_y - 0.8
    bore_y1 = y_mid + ear_outer_y + 0.8
    hinge_bore = y_cylinder(hinge_bore_r, bore_y0, bore_y1, hinge_x, hinge_z)
    latch_bore = y_cylinder(latch_bore_r, bore_y0, bore_y1, latch_x, latch_z)
    body = body.cut(hinge_bore).cut(latch_bore)

    dx = latch_x - hinge_x
    dz = latch_z - hinge_z
    span = math.sqrt(dx * dx + dz * dz)
    nx = -dz / span
    nz = dx / span
    ht = gate_thickness * 0.5

    p1 = (hinge_x + nx * ht, hinge_z + nz * ht)
    p2 = (latch_x + nx * ht, latch_z + nz * ht)
    p3 = (latch_x - nx * ht, latch_z - nz * ht)
    p4 = (hinge_x - nx * ht, hinge_z - nz * ht)

    gate_bar = (
        cq.Workplane("XZ", origin=(0, y_mid, 0))
        .moveTo(p1[0], p1[1])
        .lineTo(p2[0], p2[1])
        .lineTo(p3[0], p3[1])
        .lineTo(p4[0], p4[1])
        .close()
        .extrude(gate_width * 0.5, both=True)
    )
    hinge_boss = (
        cq.Workplane("XZ", origin=(0, y_mid, 0))
        .center(hinge_x, hinge_z)
        .circle(hinge_boss_r)
        .extrude(gate_width * 0.5, both=True)
    )
    latch_boss = (
        cq.Workplane("XZ", origin=(0, y_mid, 0))
        .center(latch_x, latch_z)
        .circle(latch_boss_r)
        .extrude(gate_width * 0.5, both=True)
    )
    gate = gate_bar.union(hinge_boss).union(latch_boss)

    gate_hinge_bore = y_cylinder(
        hinge_bore_r, y_mid - gate_width, y_mid + gate_width,
        hinge_x, hinge_z
    )
    gate_latch_bore = y_cylinder(
        latch_bore_r, y_mid - gate_width, y_mid + gate_width,
        latch_x, latch_z
    )
    gate = gate.cut(gate_hinge_bore).cut(gate_latch_bore)

    hinge_pin_y0 = y_mid - ear_outer_y - 0.30
    hinge_pin_y1 = y_mid + ear_outer_y + 0.30
    hinge_pin = y_cylinder(
        hinge_pin_r, hinge_pin_y0, hinge_pin_y1, hinge_x, hinge_z
    )
    hinge_pin = hinge_pin.union(
        y_cylinder(1.50, hinge_pin_y0 - 0.35, hinge_pin_y0, hinge_x, hinge_z)
    ).union(
        y_cylinder(1.50, hinge_pin_y1, hinge_pin_y1 + 0.35, hinge_x, hinge_z)
    )

    latch_pin_y0 = y_mid - ear_outer_y - 0.55
    latch_pin_y1 = y_mid + ear_outer_y + 0.25
    latch_pin = y_cylinder(
        latch_pin_r, latch_pin_y0, latch_pin_y1, latch_x, latch_z
    )
    latch_pin = latch_pin.union(
        y_cylinder(1.45, latch_pin_y0 - 0.45, latch_pin_y0, latch_x, latch_z)
    ).union(
        y_cylinder(1.20, latch_pin_y1, latch_pin_y1 + 0.22, latch_x, latch_z)
    )
    pull_tab = (
        cq.Workplane("XZ", origin=(0, latch_pin_y0 - 0.35, 0))
        .center(latch_x, latch_z + 1.65)
        .rect(2.2, 2.2)
        .extrude(0.35)
    )
    latch_pin = latch_pin.union(pull_tab)

    result = cq.Assembly(name="tapered_link_with_pinned_hook_gate")
    result.add(body, name="link_body_with_gate_cheeks", color=cq.Color(0.58, 0.58, 0.54))
    result.add(gate, name="pivoting_hook_gate", color=cq.Color(0.82, 0.66, 0.20))
    result.add(hinge_pin, name="retained_hinge_pin", color=cq.Color(0.30, 0.30, 0.32))
    result.add(latch_pin, name="removable_locking_pin", color=cq.Color(0.72, 0.28, 0.18))

    print("Hook lock complete: pivoting closure gate with retained hinge and removable positive locking pin.")
    return result