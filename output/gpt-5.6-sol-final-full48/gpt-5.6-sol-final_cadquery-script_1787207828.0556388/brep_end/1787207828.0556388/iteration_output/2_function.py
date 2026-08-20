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

    sketch_plane = cq.Plane(
        origin=(0.0, 15.0, 0.0),
        xDir=(1.0, 0.0, 0.0),
        normal=(0.0, -1.0, 0.0),
    )

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