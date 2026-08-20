def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)

    solids = imported.solids().vals()
    if not solids:
        raise ValueError("The input STEP file contains no solid bodies")

    original = solids[0]
    for solid in solids[1:]:
        original = original.fuse(solid)
    original = original.clean()

    bbox = original.BoundingBox()
    mirror_x = bbox.xmax
    mirrored = original.mirror("YZ", (mirror_x, 0.0, 0.0))

    result_shape = original.fuse(mirrored).clean()
    result_solids = result_shape.Solids()

    if len(result_solids) != 1:
        raise ValueError(
            f"Boolean union did not produce one body; found {len(result_solids)} solids"
        )
    if not result_shape.isValid():
        raise ValueError("The resulting mirrored and merged body is invalid")

    return cq.Workplane(obj=result_shape)