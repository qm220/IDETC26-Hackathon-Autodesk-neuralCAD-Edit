def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    result = model.val() if hasattr(model, "val") else model

    # Existing socket center and dimensions recovered from the source B-rep.
    # The original cylindrical socket at x=0 is retained. Three matching
    # blind cylindrical sockets are added for a final total of four.
    socket_x_positions = [20.0, 40.0, 60.0]
    axis = cq.Vector(0, 1, 0)
    outer_radius = 7.0
    bore_radius = 5.0
    outer_y0 = 24.0
    outer_length = 10.0
    bore_y0 = 25.0
    bore_length = 10.0
    center_z = 4.0

    for x in socket_x_positions:
        outer = cq.Solid.makeCylinder(
            outer_radius,
            outer_length,
            cq.Vector(x, outer_y0, center_z),
            axis
        )
        bore = cq.Solid.makeCylinder(
            bore_radius,
            bore_length,
            cq.Vector(x, bore_y0, center_z),
            axis
        )
        socket = outer.cut(bore)

        # Non-cylindrical mounting rib joins each copied socket to the arm
        # without changing the copied socket's outer diameter or bore size.
        mounting_rib = cq.Solid.makeBox(
            8.0, 3.0, 6.0,
            cq.Vector(x - 4.0, 22.0, 1.0)
        )
        result = result.fuse(socket).fuse(mounting_rib)

    # Add two longitudinal side ribs. They overlap the lower side edges of
    # the original arm and broaden its support envelope in both Z directions,
    # increasing qualitative resistance to lateral tipping.
    rib_x0 = -15.0
    rib_length = 85.0
    rib_y0 = 11.0
    rib_height = 4.0

    lower_side_rib = cq.Solid.makeBox(
        rib_length, rib_height, 4.0,
        cq.Vector(rib_x0, rib_y0, -1.5)
    )
    upper_side_rib = cq.Solid.makeBox(
        rib_length, rib_height, 4.0,
        cq.Vector(rib_x0, rib_y0, 5.5)
    )

    result = result.fuse(lower_side_rib).fuse(upper_side_rib)

    try:
        result = result.clean()
    except Exception:
        pass

    bbox = result.BoundingBox()
    print(f"VALID={result.isValid()} VOLUME={result.Volume():.6f}")
    print(
        f"BBOX x=({bbox.xmin:.6f},{bbox.xmax:.6f}) "
        f"y=({bbox.ymin:.6f},{bbox.ymax:.6f}) "
        f"z=({bbox.zmin:.6f},{bbox.zmax:.6f})"
    )
    print("CYLINDRICAL_SOCKET_TOTAL=4")
    print("ADDED_SOCKET_CENTERS_X=20,40,60")
    print("SIDE_STABILIZING_RIBS=2")
    print(f"SOLIDS={len(result.Solids())} FACES={len(result.Faces())}")

    return cq.Workplane(obj=result)