def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    original = model.val()

    bbox = original.BoundingBox()
    x_mid = bbox.center.x

    # Revised transverse underside rib. The prior rib reached the lowest
    # exterior datum and appeared as a hanging central block. Raise its
    # lower edge to retain clearance beneath the bracket while preserving
    # the requested symmetric 1.5 mm web thickness.
    rib_thickness = 1.5
    clearance_above_bottom = 0.55
    z_low = bbox.zmin + clearance_above_bottom
    z_high = 1.10

    # These transverse limits follow the central recessed-cavity section.
    # The sloping upper edge penetrates the cavity roof sufficiently for a
    # reliable union without extending beyond the existing overall bounds.
    y_start = 0.00
    y_end = 3.31
    y_end_at_top = 2.28

    rib = (
        cq.Workplane("YZ", origin=(x_mid, 0.0, 0.0))
        .moveTo(y_start, z_low)
        .lineTo(y_end, z_low)
        .lineTo(y_end_at_top, z_high)
        .lineTo(y_start, z_high)
        .close()
        .extrude(rib_thickness / 2.0, both=True)
    )

    result_shape = original.fuse(rib.val()).clean()

    if not result_shape.isValid():
        raise ValueError("The bracket became invalid after adding the revised rib")

    solids = result_shape.Solids()
    if len(solids) != 1:
        raise ValueError(
            "The revised rib did not merge into one continuous solid; solid count: %d"
            % len(solids)
        )

    result_bbox = result_shape.BoundingBox()
    added_volume = result_shape.Volume() - original.Volume()

    if added_volume <= 0.01:
        raise ValueError("The revised rib added no meaningful material")

    # Ensure the rib does not change the original exterior envelope.
    tolerance = 1.0e-4
    if result_bbox.zmin < bbox.zmin - tolerance:
        raise ValueError("The revised rib projects below the original bottom datum")

    print("RIB OPERATION: revised transverse underside reinforcing web")
    print("RIB THICKNESS: %.3f mm, symmetric about x=%.5f" % (rib_thickness, x_mid))
    print("RIB LOWER CLEARANCE FROM DATUM: %.3f mm" % clearance_above_bottom)
    print("ORIGINAL VOLUME: %.6f" % original.Volume())
    print("RESULT VOLUME: %.6f" % result_shape.Volume())
    print("ADDED NET VOLUME: %.6f" % added_volume)
    print("RESULT VALID:", result_shape.isValid())
    print("RESULT SOLIDS:", len(solids))
    print("RESULT FACES:", len(result_shape.Faces()))
    print("ORIGINAL Z RANGE: %.5f to %.5f" % (bbox.zmin, bbox.zmax))
    print("RESULT Z RANGE: %.5f to %.5f" % (result_bbox.zmin, result_bbox.zmax))
    print("RESULT BBOX: %.5f x %.5f x %.5f" % (
        result_bbox.xlen, result_bbox.ylen, result_bbox.zlen
    ))

    return cq.Workplane("XY").newObject([result_shape])