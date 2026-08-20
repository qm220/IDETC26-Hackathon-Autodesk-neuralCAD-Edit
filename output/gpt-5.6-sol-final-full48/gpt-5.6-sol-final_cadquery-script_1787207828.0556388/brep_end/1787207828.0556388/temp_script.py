def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)

    solids = imported.solids().vals()
    if not solids:
        raise ValueError("The imported STEP file contains no solid geometry.")

    base = solids[0]
    for solid in solids[1:]:
        base = base.fuse(solid)

    # Sketch in the wrench X-Z plane at the top surface. Local sketch Y is
    # global +Z, and extrusion proceeds from y=15 to y=0.
    sketch_plane = cq.Plane(
        origin=(0.0, 15.0, 0.0),
        xDir=(1.0, 0.0, 0.0),
        normal=(0.0, -1.0, 0.0),
    )

    # Fill the rear of the existing open-ended cutout. The replacement throat
    # is translated 10 mm toward the mouth (global -Z): its central seat is at
    # z=-120 instead of z=-110, and its R5 blends meet the unchanged gripping
    # flats at x=+/-10 and z=-125. Thus the parallel surfaces remain 20 mm apart.
    reinforcement = (
        cq.Workplane(sketch_plane)
        .moveTo(-10.0, -90.0)
        .lineTo(-10.0, -125.0)
        .threePointArc((-8.535533906, -121.464466094), (-5.0, -120.0))
        .lineTo(5.0, -120.0)
        .threePointArc((8.535533906, -121.464466094), (10.0, -125.0))
        .lineTo(10.0, -90.0)
        .close()
        .extrude(15.0)
        .val()
    )

    result_shape = base.fuse(reinforcement).clean()
    if not result_shape.isValid():
        raise ValueError("The throat reinforcement produced an invalid solid.")

    print("Open-jaw cutout depth reduced by 10 mm.")
    print("Jaw flats retained at x=-10 mm and x=+10 mm (20 mm separation).")
    print(f"Result solids: {len(result_shape.Solids())}")
    print(f"Result valid: {result_shape.isValid()}")

    return cq.Workplane("XY").newObject([result_shape])