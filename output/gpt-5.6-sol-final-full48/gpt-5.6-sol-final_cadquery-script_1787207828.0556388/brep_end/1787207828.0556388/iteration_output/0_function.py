def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    original = model.val()

    # The wrench lies in the global X-Z plane and spans y=0..15 mm.
    # Add material between the original throat and a replacement throat
    # translated 10 mm toward the open mouth (global -Z).
    sketch_plane = cq.Plane(
        origin=(0.0, 15.0, 0.0),
        xDir=(1.0, 0.0, 0.0),
        normal=(0.0, -1.0, 0.0)
    )

    reinforcement = (
        cq.Workplane(sketch_plane)
        .moveTo(-10.0, -100.0)
        .lineTo(-10.0, -125.0)
        .threePointArc((-8.535533906, -121.464466094), (-5.0, -120.0))
        .lineTo(5.0, -120.0)
        .threePointArc((8.535533906, -121.464466094), (10.0, -125.0))
        .lineTo(10.0, -100.0)
        .close()
        .extrude(15.0)
    )

    result = model.union(reinforcement).clean()
    final_shape = result.val()

    print(f"Original volume: {original.Volume():.6f} mm^3")
    print(f"Modified volume: {final_shape.Volume():.6f} mm^3")
    print(f"Added volume: {final_shape.Volume() - original.Volume():.6f} mm^3")
    print(f"Result valid: {final_shape.isValid()}")
    print("Open-jaw throat shifted 10 mm toward the mouth; jaw flats remain at x=-10 and x=10 mm.")

    return result