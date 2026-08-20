def my_cad_function(args):
    import os
    import math
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    original = imported.val() if hasattr(imported, "val") else imported

    # Add a simple pivoting safety gate across the open hook throat. The gate
    # is modeled in its closed position as a separate movable component.
    pivot = cq.Vector(64.7, 0.0, 10.7)
    gate_end = cq.Vector(71.55, 0.0, 14.05)

    # Provide a narrow central hinge recess while retaining material on both
    # sides of the hook. This is the minimum alteration needed for the gate.
    recess_radius = 1.85
    recess_y0 = -1.25
    recess_width = 2.50
    recess = cq.Solid.makeCylinder(
        recess_radius,
        recess_width,
        cq.Vector(pivot.x, recess_y0, pivot.z),
        cq.Vector(0, 1, 0)
    )
    modified_body = original.cut(recess)

    # Transverse hinge pin fixed into the side material of the hook.
    pin_radius = 0.95
    pin_y0 = -4.0
    pin_length = 8.0
    pin = cq.Solid.makeCylinder(
        pin_radius,
        pin_length,
        cq.Vector(pivot.x, pin_y0, pivot.z),
        cq.Vector(0, 1, 0)
    )

    # Low-profile retaining heads make the pivot visually and mechanically
    # explicit and prevent the gate eye from sliding off the pin.
    collar_radius = 1.30
    collar_width = 0.55
    collar_a = cq.Solid.makeCylinder(
        collar_radius,
        collar_width,
        cq.Vector(pivot.x, pin_y0, pivot.z),
        cq.Vector(0, 1, 0)
    )
    collar_b = cq.Solid.makeCylinder(
        collar_radius,
        collar_width,
        cq.Vector(pivot.x, pin_y0 + pin_length - collar_width, pivot.z),
        cq.Vector(0, 1, 0)
    )
    fixed_pin = pin.fuse(collar_a).fuse(collar_b)
    modified_body = modified_body.fuse(fixed_pin)

    # Gate hinge eye, located inside the central recess with running clearance
    # around the fixed transverse pin.
    eye_outer_radius = 1.68
    eye_bore_radius = 1.08
    gate_thickness = 2.10
    gate_y0 = -gate_thickness / 2.0
    eye_outer = cq.Solid.makeCylinder(
        eye_outer_radius,
        gate_thickness,
        cq.Vector(pivot.x, gate_y0, pivot.z),
        cq.Vector(0, 1, 0)
    )
    eye_bore = cq.Solid.makeCylinder(
        eye_bore_radius,
        gate_thickness + 0.4,
        cq.Vector(pivot.x, gate_y0 - 0.2, pivot.z),
        cq.Vector(0, 1, 0)
    )
    gate_eye = eye_outer.cut(eye_bore)

    # Slender gate member reaches from the pivot eye to immediately behind
    # the retaining lug, closing the escape path while avoiding overlap with
    # the original load-bearing lug.
    gate_vector = gate_end.sub(pivot)
    gate_length = gate_vector.Length
    gate_direction = gate_vector.normalized()
    gate_bar = cq.Solid.makeCylinder(
        0.80,
        gate_length,
        pivot,
        gate_direction
    )

    gate = gate_eye.fuse(gate_bar)

    # Keep the gate as a separate solid so the output represents an actual
    # pivoting mechanism rather than a permanently fused bridge.
    result = cq.Compound.makeCompound([modified_body, gate])

    print("LOCKING GATE ADDED")
    print("RESULT VALID:", result.isValid())
    print("SOLIDS:", len(result.Solids()), "FACES:", len(result.Faces()))
    print("PIVOT: (%.3f, %.3f, %.3f)" % (pivot.x, pivot.y, pivot.z))
    print("GATE END: (%.3f, %.3f, %.3f)" % (gate_end.x, gate_end.y, gate_end.z))

    return cq.Workplane("XY").add(result)
