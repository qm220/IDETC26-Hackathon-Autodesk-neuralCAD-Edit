def my_cad_function(args):
    import os

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    imported_shape = imported.val() if hasattr(imported, "val") else imported
    solids = imported_shape.Solids()
    base = solids[0] if solids else imported_shape

    # Inspect and bind the planned FACE indices to the actual imported geometry.
    print("Imported model valid:", base.isValid())
    print("Imported solids:", len(solids), "faces:", len(base.Faces()))
    bb = base.BoundingBox()
    print("Model bounds: x=(%.3f, %.3f), y=(%.3f, %.3f), z=(%.3f, %.3f)" %
          (bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax))
    for i, face in enumerate(base.Faces()):
        c = face.Center()
        fb = face.BoundingBox()
        try:
            gt = face.geomType()
        except Exception:
            gt = "UNKNOWN"
        print("FACE %d type=%s center=(%.3f,%.3f,%.3f) bounds=[%.3f,%.3f]x[%.3f,%.3f]x[%.3f,%.3f]" %
              (i, gt, c.x, c.y, c.z, fb.xmin, fb.xmax, fb.ymin, fb.ymax,
               fb.zmin, fb.zmax))

    # The STEP analysis identifies the hook seat at (66.75, 0, 11), with
    # inner radius 3 and outer radius 9. Place the pivot in the thick root-side
    # annulus, clear of the functional radius-3 seating surface.
    pivot_x = 60.50
    pivot_z = 16.00
    boss_radius = 3.40
    boss_outer_y = 5.50
    boss_inner_y = 2.70
    bore_radius = 1.35

    # Paired mounting bosses penetrate the existing side faces slightly so the
    # Boolean union is structural rather than merely tangent.
    boss_neg = cq.Solid.makeCylinder(
        boss_radius, boss_outer_y - boss_inner_y,
        cq.Vector(pivot_x, -boss_outer_y, pivot_z), cq.Vector(0, 1, 0)
    )
    boss_pos = cq.Solid.makeCylinder(
        boss_radius, boss_outer_y - boss_inner_y,
        cq.Vector(pivot_x, boss_inner_y, pivot_z), cq.Vector(0, 1, 0)
    )
    modified_base = base.fuse(boss_neg).fuse(boss_pos)

    # Coaxial transverse pivot bore, parallel to CAD Y.
    pivot_bore = cq.Solid.makeCylinder(
        bore_radius, 12.0, cq.Vector(pivot_x, -6.0, pivot_z), cq.Vector(0, 1, 0)
    )
    modified_base = modified_base.cut(pivot_bore)
    print("Modified base valid:", modified_base.isValid(),
          "faces:", len(modified_base.Faces()))

    # Closed gate geometry. Two plate arms straddle the hook side faces while a
    # transverse rounded bar bridges the throat and lands just above the toe.
    end_x = 72.35
    end_z = 16.35
    arm_half_width = 1.10
    arm_thickness = 1.25
    arm_center_y = 6.425

    # Unit normal to the slightly inclined arm centerline in the XZ plane.
    dx = end_x - pivot_x
    dz = end_z - pivot_z
    length = (dx * dx + dz * dz) ** 0.5
    nx = -dz / length
    nz = dx / length
    outline_xz = [
        (pivot_x + nx * arm_half_width, pivot_z + nz * arm_half_width),
        (end_x + nx * arm_half_width, end_z + nz * arm_half_width),
        (end_x - nx * arm_half_width, end_z - nz * arm_half_width),
        (pivot_x - nx * arm_half_width, pivot_z - nz * arm_half_width)
    ]

    def make_arm(y_center):
        # For a plane normal to +Y with xDir +X, local plane Y corresponds -Z.
        plane = cq.Plane(origin=(0, y_center, 0), xDir=(1, 0, 0), normal=(0, 1, 0))
        local_pts = [(x, -z) for x, z in outline_xz]
        plate = (cq.Workplane(plane)
                 .polyline(local_pts).close()
                 .extrude(arm_thickness / 2.0, both=True).val())
        y0 = y_center - arm_thickness / 2.0
        pivot_pad = cq.Solid.makeCylinder(
            2.55, arm_thickness, cq.Vector(pivot_x, y0, pivot_z), cq.Vector(0, 1, 0)
        )
        end_pad = cq.Solid.makeCylinder(
            1.55, arm_thickness, cq.Vector(end_x, y0, end_z), cq.Vector(0, 1, 0)
        )
        arm = plate.fuse(pivot_pad).fuse(end_pad)
        arm_hole = cq.Solid.makeCylinder(
            1.25, arm_thickness + 0.4,
            cq.Vector(pivot_x, y0 - 0.2, pivot_z), cq.Vector(0, 1, 0)
        )
        return arm.cut(arm_hole)

    arm_pos = make_arm(arm_center_y)
    arm_neg = make_arm(-arm_center_y)

    # The closing bar is above the z=15 toe cap with a small running clearance.
    # Its root-side shoulder prevents a carried load from directly escaping.
    crossbar = cq.Solid.makeCylinder(
        1.30, 2.0 * arm_center_y + arm_thickness,
        cq.Vector(end_x, -arm_center_y - arm_thickness / 2.0, end_z),
        cq.Vector(0, 1, 0)
    )
    gate = arm_neg.fuse(arm_pos).fuse(crossbar)

    # Removable pivot pin with a head and opposite retaining collar.
    pin_radius = 1.15
    pin_y0 = -7.45
    pin_length = 14.90
    pin_shank = cq.Solid.makeCylinder(
        pin_radius, pin_length, cq.Vector(pivot_x, pin_y0, pivot_z), cq.Vector(0, 1, 0)
    )
    pin_head = cq.Solid.makeCylinder(
        1.90, 0.80, cq.Vector(pivot_x, pin_y0 - 0.80, pivot_z), cq.Vector(0, 1, 0)
    )
    pin_collar = cq.Solid.makeCylinder(
        1.65, 0.65, cq.Vector(pivot_x, pin_y0 + pin_length, pivot_z), cq.Vector(0, 1, 0)
    )
    pin = pin_shank.fuse(pin_head).fuse(pin_collar)

    # Simplified torsion spring representation around the pivot, outside the
    # positive-side arm. It remains a separate assembly component.
    spring_y = 7.45
    spring = cq.Solid.makeTorus(
        1.75, 0.24, cq.Vector(pivot_x, spring_y, pivot_z), cq.Vector(0, 1, 0)
    )
    spring_leg_gate = cq.Solid.makeCylinder(
        0.24, 3.2, cq.Vector(pivot_x + 1.75, spring_y, pivot_z), cq.Vector(1, 0, 0)
    )
    spring_leg_body = cq.Solid.makeCylinder(
        0.24, 3.0, cq.Vector(pivot_x - 1.75, spring_y, pivot_z), cq.Vector(-0.35, 0, -0.94)
    )
    spring = spring.fuse(spring_leg_gate).fuse(spring_leg_body)

    print("Gate valid:", gate.isValid(), "pin valid:", pin.isValid())
    print("Pivot axis: (%.3f, Y, %.3f); gate landing: (%.3f, Y, %.3f)" %
          (pivot_x, pivot_z, end_x, end_z))
    print("Seat clearance check: pivot-to-seat-center distance = %.3f mm" %
          (((pivot_x - 66.75) ** 2 + (pivot_z - 11.0) ** 2) ** 0.5))

    result = cq.Assembly(name="hook_safety_gate_assembly")
    result.add(modified_base, name="lever_with_pivot_bosses",
               color=cq.Color(0.35, 0.55, 0.72))
    result.add(gate, name="self_closing_U_gate",
               color=cq.Color(0.90, 0.55, 0.12))
    result.add(pin, name="removable_pivot_pin",
               color=cq.Color(0.72, 0.72, 0.75))
    result.add(spring, name="torsion_spring",
               color=cq.Color(0.82, 0.68, 0.18))
    return result