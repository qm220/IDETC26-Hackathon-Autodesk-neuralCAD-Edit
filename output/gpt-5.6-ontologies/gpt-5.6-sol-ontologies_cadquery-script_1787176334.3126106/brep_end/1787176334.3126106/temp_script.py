def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    initial_volume = shape.Volume()
    bbox = shape.BoundingBox()

    # Add five transverse through-cutouts to the tapered structural arm.
    # Their diameters decrease toward the narrower hooked end, retaining
    # substantial ligaments around each opening and preserving both interfaces.
    cutouts = [
        (-45.0, 7.5, 3.2),
        (-22.0, 7.5, 3.0),
        (1.0,   7.5, 2.7),
        (24.0,  7.5, 2.3),
        (44.0,  7.5, 1.8),
    ]

    edited = shape
    cutter_length = bbox.ylen + 4.0
    cutter_start_y = bbox.ymin - 2.0

    for x_pos, z_pos, radius in cutouts:
        cutter = cq.Solid.makeCylinder(
            radius,
            cutter_length,
            cq.Vector(x_pos, cutter_start_y, z_pos),
            cq.Vector(0, 1, 0)
        )
        edited = edited.cut(cutter)

    final_volume = edited.Volume()
    print(f"Initial valid: {shape.isValid()}")
    print(f"Final valid: {edited.isValid()}")
    print(f"Initial volume: {initial_volume:.6f} mm^3")
    print(f"Final volume: {final_volume:.6f} mm^3")
    print(f"Removed volume: {initial_volume - final_volume:.6f} mm^3")
    print(f"Weight-reduction cutouts added: {len(cutouts)}")
    print(f"Final solids: {len(edited.Solids())}, faces: {len(edited.Faces())}")

    return cq.Workplane("XY").newObject([edited])