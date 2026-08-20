def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    original = model.val()

    # Add one central tapered structural rib beneath the clevis region.
    # The rib is centered between the two clevis ears and has an exact
    # thickness of 1.5 mm in the global X direction.
    rib_thickness = 1.5
    clevis_center_x = 6.1226
    rib_x0 = clevis_center_x - rib_thickness / 2.0

    rib_plane = cq.Plane(
        origin=(rib_x0, 0.0, 0.0),
        xDir=(0.0, 1.0, 0.0),
        normal=(1.0, 0.0, 0.0)
    )

    # Coordinates on this YZ-oriented plane are (global Y, global Z).
    # The profile slightly overlaps the existing rear wall and the lower
    # clevis/body transition so the resulting rib is structurally fused.
    rib = (
        cq.Workplane(rib_plane)
        .polyline([
            (0.05, -1.04),
            (0.05, 1.08),
            (3.65, -0.65),
            (3.65, -1.04)
        ])
        .close()
        .extrude(rib_thickness)
    )

    result_shape = original.fuse(rib.val()).clean()
    result = cq.Workplane("XY").newObject([result_shape])

    old_bb = original.BoundingBox()
    new_bb = result_shape.BoundingBox()
    rib_bb = rib.val().BoundingBox()
    print("ORIGINAL VALID:", original.isValid())
    print("RESULT VALID:", result_shape.isValid())
    print("RESULT SOLIDS:", len(result_shape.Solids()))
    print("ORIGINAL VOLUME: %.6f" % original.Volume())
    print("RESULT VOLUME: %.6f" % result_shape.Volume())
    print("ADDED NET VOLUME: %.6f" % (result_shape.Volume() - original.Volume()))
    print("RIB NOMINAL THICKNESS X: %.4f mm" % rib_bb.xlen)
    print("RIB BBOX: x=(%.4f, %.4f) y=(%.4f, %.4f) z=(%.4f, %.4f)" %
          (rib_bb.xmin, rib_bb.xmax, rib_bb.ymin, rib_bb.ymax,
           rib_bb.zmin, rib_bb.zmax))
    print("ORIGINAL BBOX: x=(%.4f, %.4f) y=(%.4f, %.4f) z=(%.4f, %.4f)" %
          (old_bb.xmin, old_bb.xmax, old_bb.ymin, old_bb.ymax,
           old_bb.zmin, old_bb.zmax))
    print("RESULT BBOX: x=(%.4f, %.4f) y=(%.4f, %.4f) z=(%.4f, %.4f)" %
          (new_bb.xmin, new_bb.xmax, new_bb.ymin, new_bb.ymax,
           new_bb.zmin, new_bb.zmax))

    return result