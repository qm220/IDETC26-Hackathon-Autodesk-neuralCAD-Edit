def my_cad_function(args):
    import os
    import cadquery as cq

    model = cq.importers.importStep(os.path.expanduser(args["input_file"]))

    center_x = 6.1226
    rib_thickness = 1.5

    rib_plane = cq.Plane(
        origin=(center_x - rib_thickness / 2.0, 0.0, 0.0),
        xDir=(0.0, 1.0, 0.0),
        normal=(1.0, 0.0, 0.0),
    )

    rib_profile = [
        (0.08, -1.60),
        (0.08, 1.50),
        (2.22, 1.50),
        (3.65, -1.60),
    ]

    rib = (
        cq.Workplane(rib_plane)
        .polyline(rib_profile)
        .close()
        .extrude(rib_thickness)
    )

    result = model.union(rib)
    return result