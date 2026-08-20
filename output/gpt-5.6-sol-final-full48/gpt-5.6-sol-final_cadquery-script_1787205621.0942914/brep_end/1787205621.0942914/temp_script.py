def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val()
    solids = list(root.Solids())

    print("Imported solid count:", len(solids))
    for i, solid in enumerate(solids):
        bb = solid.BoundingBox()
        print(
            "solid %d bbox: x=(%.3f, %.3f) y=(%.3f, %.3f) z=(%.3f, %.3f) vol=%.3f"
            % (i, bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax, solid.Volume())
        )

    if len(solids) < 20:
        raise ValueError("Expected at least 20 solids in the source assembly")

    # model.json identifies solid 12 as the removable upper cord-holder/guide
    # candidate and solid 17 as the existing black U-shaped handle/stand.
    cordholder_index = 12
    stand_index = 17
    shell_index = 0

    shell = solids[shell_index]
    stand = solids[stand_index]
    shell_bb = shell.BoundingBox()
    stand_bb = stand.BoundingBox()

    # The housing longitudinal direction is semantic Y. Mirror the existing
    # complete stand about the center plane between the housing end walls.
    longitudinal_center = 0.5 * (shell_bb.ymin + shell_bb.ymax)
    mirrored_stand = (
        cq.Workplane("XY")
        .newObject([stand])
        .mirror(mirrorPlane="XZ", basePointVector=(0, longitudinal_center, 0), union=False)
        .val()
    )

    mirrored_bb = mirrored_stand.BoundingBox()
    print("Housing longitudinal center Y:", longitudinal_center)
    print("Original stand Y range:", stand_bb.ymin, stand_bb.ymax)
    print("Mirrored stand Y range:", mirrored_bb.ymin, mirrored_bb.ymax)

    # Establish one common horizontal support plane. Raise it slightly above
    # the tangent bottom of the curved stand to produce useful finite-area,
    # coplanar feet while preserving the arms and pivot regions.
    stand_height = stand_bb.zmax - stand_bb.zmin
    cut_rise = max(2.0, min(8.0, 0.055 * stand_height))
    support_z = stand_bb.zmin + cut_rise

    all_bb = root.BoundingBox()
    margin_xy = max(all_bb.xlen, all_bb.ylen, 100.0) * 2.0
    keep_height = max(all_bb.zmax - support_z + 50.0, 100.0)
    keep_box = (
        cq.Workplane("XY")
        .box(2.0 * margin_xy, 2.0 * margin_xy, keep_height, centered=(True, True, False))
        .translate((0, 0, support_z))
        .val()
    )

    trimmed_original = stand.intersect(keep_box)
    trimmed_mirrored = mirrored_stand.intersect(keep_box)

    if trimmed_original.isNull() or trimmed_mirrored.isNull():
        raise ValueError("Stand trimming produced a null shape")

    print("Common stand support plane Z:", support_z)
    print("Original trimmed minimum Z:", trimmed_original.BoundingBox().zmin)
    print("Mirrored trimmed minimum Z:", trimmed_mirrored.BoundingBox().zmin)

    # Preserve all source solids except the identified Cordholder and the
    # untrimmed source stand. Add the two independently trimmed stand solids.
    result_shapes = []
    for i, solid in enumerate(solids):
        if i in (cordholder_index, stand_index):
            continue
        result_shapes.append(solid)

    result_shapes.append(trimmed_original)
    result_shapes.append(trimmed_mirrored)

    result = cq.Compound.makeCompound(result_shapes)
    print("Removed source solid:", cordholder_index)
    print("Replaced stand solid %d with two mirrored, coplanar-foot stands" % stand_index)
    print("Output solid count:", len(result.Solids()))
    print("Output valid:", result.isValid())
    return result