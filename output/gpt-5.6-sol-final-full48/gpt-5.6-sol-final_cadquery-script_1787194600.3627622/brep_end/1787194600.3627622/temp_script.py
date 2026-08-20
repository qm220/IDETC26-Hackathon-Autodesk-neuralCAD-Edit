def my_cad_function(args):
    import os
    import cadquery as cq

    # Load the untouched source model.
    model = cq.importers.importStep(os.path.expanduser(args["input_file"]))

    # Central symmetry plane between the two clevis ears is approximately
    # X = 6.1226 mm.  Add one nominally 1.5 mm thick rib inside the underside
    # relief, extending from the base/cavity floor to the inclined central
    # clevis-support shell.  Its limited Z extent keeps it clear of all four
    # mounting bores and the elevated clevis pin bores.
    center_x = 6.1226
    rib_thickness = 1.5

    rib_plane = cq.Plane(
        origin=(center_x - rib_thickness / 2.0, 0.0, 0.0),
        xDir=(0.0, 1.0, 0.0),
        normal=(1.0, 0.0, 0.0),
    )

    # Coordinates below are (Y, Z) on the YZ workplane.  The lower edge
    # penetrates the cavity floor slightly, while the inclined upper edge
    # penetrates the existing central support panel to ensure an integral,
    # load-transferring union.
    rib_profile = [
        (0.08, -1.60),
        (0.08,  1.50),
        (2.22,  1.50),
        (3.65, -1.60),
    ]

    rib = (
        cq.Workplane(rib_plane)
        .polyline(rib_profile)
        .close()
        .extrude(rib_thickness)
    )

    result = model.union(rib)

    solid = result.val()
    bb = solid.BoundingBox()
    print("RIB_ADDED", "thickness", rib_thickness, "center_x", center_x)
    print("VALID", solid.isValid(), "VOLUME", solid.Volume())
    print("BBOX", (bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax))

    return result