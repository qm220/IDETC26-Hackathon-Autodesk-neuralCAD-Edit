def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()
    solids = list(shape.Solids())

    cradle = None
    cordholder = None

    for solid in solids:
        bb = solid.BoundingBox()
        vol = solid.Volume()

        if (240.0 < bb.xlen < 265.0 and
                20.0 < bb.ylen < 30.0 and
                180.0 < bb.zlen < 200.0 and
                250000.0 < vol < 350000.0):
            cradle = solid

        if (15.0 < bb.xlen < 25.0 and
                85.0 < bb.ylen < 100.0 and
                34.0 < bb.zlen < 42.0 and
                30000.0 < vol < 55000.0 and
                bb.zmin > 75.0):
            cordholder = solid

    if cradle is None:
        raise ValueError("Could not identify the existing exterior U-shaped cradle")
    if cordholder is None:
        raise ValueError("Could not identify the internal U-shaped Cordholder")

    cb = cradle.BoundingBox()
    housing = max(solids, key=lambda s: s.Volume())
    hb = housing.BoundingBox()

    housing_y_mid = (hb.ymin + hb.ymax) / 2.0
    cradle_y_mid = (cb.ymin + cb.ymax) / 2.0
    mirrored_y_mid = 2.0 * housing_y_mid - cradle_y_mid
    copy_translation = mirrored_y_mid - cradle_y_mid

    ground_z = -145.0
    overall_bb = shape.BoundingBox()
    keep_box = cq.Solid.makeBox(
        overall_bb.xlen + 400.0,
        overall_bb.ylen + 400.0,
        overall_bb.zmax - ground_z + 200.0,
        cq.Vector(
            overall_bb.xmin - 200.0,
            overall_bb.ymin - 200.0,
            ground_z
        )
    )

    trimmed_existing = cradle.intersect(keep_box)
    copied_cradle = cradle.moved(
        cq.Location(cq.Vector(0.0, copy_translation, 0.0))
    )
    trimmed_copy = copied_cradle.intersect(keep_box)

    if not trimmed_existing.isValid() or not trimmed_copy.isValid():
        raise ValueError("One or both trimmed stand bodies are invalid")

    output_parts = []
    for solid in solids:
        if solid is cradle or solid is cordholder:
            continue
        output_parts.append(solid)

    output_parts.extend(trimmed_existing.Solids())
    output_parts.extend(trimmed_copy.Solids())

    result = cq.Compound.makeCompound(output_parts)

    print("Original solid count:", len(solids))
    print("Removed Cordholder bbox:",
          (cordholder.BoundingBox().xmin,
           cordholder.BoundingBox().ymin,
           cordholder.BoundingBox().zmin),
          (cordholder.BoundingBox().xmax,
           cordholder.BoundingBox().ymax,
           cordholder.BoundingBox().zmax))
    print("Existing cradle Y center:", cradle_y_mid)
    print("Added cradle Y center:", mirrored_y_mid)
    print("Cradle translation Y:", copy_translation)
    print("Common stand ground Z:", ground_z)
    print("Output solid count:", len(result.Solids()))
    print("Output valid:", result.isValid())

    return cq.Workplane("XY").newObject([result])