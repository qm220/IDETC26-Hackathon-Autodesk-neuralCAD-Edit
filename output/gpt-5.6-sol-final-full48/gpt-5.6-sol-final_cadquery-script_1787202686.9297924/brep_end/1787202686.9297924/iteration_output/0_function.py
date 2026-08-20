def my_cad_function(args):
    import os

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)

    original_shape = model.val()
    original_volume = original_shape.Volume()
    bbox = original_shape.BoundingBox()

    # Three longitudinal capsule-shaped lightening openings. Coordinates are
    # defined on the global XZ mid-plane and cut through the full Y thickness.
    slots = [
        (-41.0, 7.5, 22.0, 5.0),   # x extent approximately -52 to -30
        (-11.5, 7.5, 23.0, 4.5),   # x extent approximately -23 to 0
        (21.5, 7.5, 27.0, 3.5),    # x extent approximately 8 to 35
    ]

    result = model
    cut_depth = max(100.0, 2.0 * bbox.ylen + 10.0)

    for center_x, center_z, length, width in slots:
        cutter = (
            cq.Workplane("XZ")
            .center(center_x, center_z)
            .slot2D(length, width, angle=0)
            .extrude(cut_depth, both=True)
        )
        result = result.cut(cutter)

    final_shape = result.val()
    print(f"Original volume: {original_volume:.6f} mm^3")
    print(f"Final volume: {final_shape.Volume():.6f} mm^3")
    print(f"Removed volume: {original_volume - final_shape.Volume():.6f} mm^3")
    print(f"Result valid: {final_shape.isValid()}")
    print(f"Connected solids: {len(final_shape.Solids())}")
    print("Created three separated capsule-shaped through-cut lightening openings in the tapered arm.")

    return result