def my_cad_function(args):
    import os
    import math

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    original = imported.val()
    bbox = original.BoundingBox()

    # The original lever is aligned with X, with the hook at the +X end.
    # Dimensions below scale from the existing part while remaining close to
    # the provisional dimensions in the operation plan.
    x_max = bbox.xmax
    y_mid = (bbox.ymin + bbox.ymax) * 0.5
    z_mid = (bbox.zmin + bbox.zmax) * 0.5
    span_x = bbox.xlen

    pin_d = 2.0
    pin_r = pin_d * 0.5
    running_clearance = 0.20
    gate_width = 2.4
    gate_thickness = 1.8
    hinge_outer_r = 3.0

    # Closed gate location across the visible mouth of the hook. The hook
    # opening is on the +Y side in the supplied model views.
    hinge_x = x_max - max(12.5, span_x * 0.085)
    hinge_y = y_mid + 3.5
    tip_x = x_max - 4.2
    tip_y = y_mid + 4.5

    dx = tip_x - hinge_x
    dy = tip_y - hinge_y
    length = math.sqrt(dx * dx + dy * dy)
    nx = -dy / length
    ny = dx / length
    half_t = gate_thickness * 0.5

    # Add two stationary hinge ears. They straddle the central gate and blend
    # into the existing hook root by overlapping the original hook material.
    ear_inner = gate_width * 0.5 + running_clearance
    ear_width = 1.35
    lower_ear_z0 = z_mid - ear_inner - ear_width
    upper_ear_z0 = z_mid + ear_inner

    lower_ear = cq.Workplane("XY", origin=(0, 0, lower_ear_z0)).center(hinge_x, hinge_y).circle(hinge_outer_r).extrude(ear_width)
    upper_ear = cq.Workplane("XY", origin=(0, 0, upper_ear_z0)).center(hinge_x, hinge_y).circle(hinge_outer_r).extrude(ear_width)

    body = cq.Workplane(obj=original).union(lower_ear).union(upper_ear)

    # A compact additive catch on the inward face of the existing nose. It
    # provides a positive stop for outward gate motion and a rounded lead-in.
    catch_x = tip_x + 0.15
    catch_y = tip_y - 0.90
    catch = (
        cq.Workplane("XY", origin=(0, 0, z_mid - 2.7))
        .center(catch_x, catch_y)
        .rect(1.7, 2.0)
        .extrude(5.4)
    )
    catch_leadin = (
        cq.Workplane("XY", origin=(0, 0, z_mid - 2.7))
        .center(catch_x - 0.75, catch_y - 0.25)
        .circle(0.85)
        .extrude(5.4)
    )
    body = body.union(catch).union(catch_leadin)

    # Bore through the stationary ears. The bore is deliberately local to the
    # new hinge support and is coaxial with the gate pivot.
    hinge_bore = cq.Workplane("XY", origin=(0, 0, z_mid - 5.0)).center(hinge_x, hinge_y).circle(pin_r + 0.10).extrude(10.0)
    body = body.cut(hinge_bore)

    # Gate profile: a straight, rounded bar with an enlarged pivot boss and a
    # small inward-facing latch toe at its free end.
    p1a = (hinge_x + nx * half_t, hinge_y + ny * half_t)
    p2a = (tip_x + nx * half_t, tip_y + ny * half_t)
    p2b = (tip_x - nx * half_t, tip_y - ny * half_t)
    p1b = (hinge_x - nx * half_t, hinge_y - ny * half_t)

    gate_z0 = z_mid - gate_width * 0.5
    gate_bar = (
        cq.Workplane("XY", origin=(0, 0, gate_z0))
        .moveTo(p1a[0], p1a[1])
        .lineTo(p2a[0], p2a[1])
        .lineTo(p2b[0], p2b[1])
        .lineTo(p1b[0], p1b[1])
        .close()
        .extrude(gate_width)
    )
    pivot_boss = cq.Workplane("XY", origin=(0, 0, gate_z0)).center(hinge_x, hinge_y).circle(2.35).extrude(gate_width)
    rounded_tip = cq.Workplane("XY", origin=(0, 0, gate_z0)).center(tip_x, tip_y).circle(half_t).extrude(gate_width)

    # The latch toe overlaps the nose catch in projection, preventing the gate
    # from opening outward while still presenting a cammed inward side.
    latch_toe = (
        cq.Workplane("XY", origin=(0, 0, gate_z0))
        .center(tip_x - 0.15, tip_y - 0.75)
        .circle(0.85)
        .extrude(gate_width)
    )
    gate = gate_bar.union(pivot_boss).union(rounded_tip).union(latch_toe)
    gate_bore = cq.Workplane("XY", origin=(0, 0, gate_z0 - 0.5)).center(hinge_x, hinge_y).circle(pin_r + 0.12).extrude(gate_width + 1.0)
    gate = gate.cut(gate_bore)

    # Retained hinge pin with low-profile heads on both sides.
    pin_z0 = lower_ear_z0 - 0.35
    pin_length = (upper_ear_z0 + ear_width + 0.35) - pin_z0
    pin = cq.Workplane("XY", origin=(0, 0, pin_z0)).center(hinge_x, hinge_y).circle(pin_r).extrude(pin_length)
    lower_head = cq.Workplane("XY", origin=(0, 0, pin_z0 - 0.35)).center(hinge_x, hinge_y).circle(1.55).extrude(0.35)
    upper_head = cq.Workplane("XY", origin=(0, 0, pin_z0 + pin_length)).center(hinge_x, hinge_y).circle(1.55).extrude(0.35)
    pin = pin.union(lower_head).union(upper_head)

    result = cq.Assembly(name="tapered_link_with_hook_lock")
    result.add(body, name="modified_link_body", color=cq.Color(0.58, 0.58, 0.54))
    result.add(gate, name="pivoting_safety_gate", color=cq.Color(0.82, 0.66, 0.20))
    result.add(pin, name="retained_hinge_pin", color=cq.Color(0.30, 0.30, 0.32))

    print("Added a closed pivoting safety gate, paired hinge ears, retained pin, and positive nose catch.")
    print("Original bbox: X %.2f..%.2f, Y %.2f..%.2f, Z %.2f..%.2f" % (bbox.xmin, bbox.xmax, bbox.ymin, bbox.ymax, bbox.zmin, bbox.zmax))
    print("Hinge center: (%.2f, %.2f, %.2f), gate span: %.2f mm" % (hinge_x, hinge_y, z_mid, length))
    return result