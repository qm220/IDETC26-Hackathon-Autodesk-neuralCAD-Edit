def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    original = model.val()

    bbox = original.BoundingBox()
    x_mid = bbox.center.x

    # Add a transverse web beneath the clevis root. The YZ sketch defines
    # the rib's profile inside the underside recess, while the symmetric
    # extrusion supplies the requested 1.5 mm thickness along X.
    # The sloped upper edge follows the nearby supporting-shell slope.
    z_low = -1.48
    z_high = 1.10
    y_bottom = 0.00
    y_top_low_z = 3.31
    y_top_high_z = 2.28

    rib = (
        cq.Workplane("YZ", origin=(x_mid, 0.0, 0.0))
        .moveTo(y_bottom, z_low)
        .lineTo(y_top_low_z, z_low)
        .lineTo(y_top_high_z, z_high)
        .lineTo(y_bottom, z_high)
        .close()
        .extrude(0.75, both=True)
    )

    rib_shape = rib.val()
    result_shape = original.fuse(rib_shape).clean()

    if not result_shape.isValid():
        raise ValueError("The bracket became invalid after adding the transverse rib")

    solids = result_shape.Solids()
    if len(solids) != 1:
        raise ValueError(
            "The rib did not merge into one continuous solid; resulting solid count: %d"
            % len(solids)
        )

    result_bbox = result_shape.BoundingBox()
    added_volume = result_shape.Volume() - original.Volume()

    print("RIB OPERATION: transverse underside reinforcing web")
    print("RIB THICKNESS: 1.500 mm, symmetric about x=%.5f" % x_mid)
    print("ORIGINAL VOLUME: %.6f" % original.Volume())
    print("RESULT VOLUME: %.6f" % result_shape.Volume())
    print("ADDED NET VOLUME: %.6f" % added_volume)
    print("RESULT VALID:", result_shape.isValid())
    print("RESULT SOLIDS:", len(solids))
    print("RESULT FACES:", len(result_shape.Faces()))
    print("RESULT BBOX: %.5f x %.5f x %.5f" % (
        result_bbox.xlen, result_bbox.ylen, result_bbox.zlen
    ))

    if added_volume <= 0.01:
        raise ValueError("The proposed rib added no meaningful material")

    return cq.Workplane("XY").newObject([result_shape])