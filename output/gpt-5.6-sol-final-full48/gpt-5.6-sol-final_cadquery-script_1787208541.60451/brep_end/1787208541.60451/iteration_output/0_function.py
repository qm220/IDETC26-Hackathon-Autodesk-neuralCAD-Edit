def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)

    # Consolidate the imported model into its original solid body.
    solids = imported.solids().vals()
    if not solids:
        raise ValueError("The input STEP file contains no solid bodies")

    original = solids[0]
    for solid in solids[1:]:
        original = original.fuse(solid)
    original = original.clean()

    # The non-rounded terminal is the maximum-X planar end face. Mirror about
    # the coincident YZ-oriented plane at that end.
    bbox = original.BoundingBox()
    mirror_x = bbox.xmax
    mirrored = original.mirror("YZ", (mirror_x, 0.0, 0.0))

    # Fuse the reflected copy to the original across the complete end face and
    # refine the result to remove the obsolete coplanar interface.
    result_shape = original.fuse(mirrored).clean()

    result_solids = result_shape.Solids()
    print(f"Mirror plane: X = {mirror_x:.6f}")
    print(f"Original bounds: X=[{bbox.xmin:.6f}, {bbox.xmax:.6f}]")
    print(f"Result solids: {len(result_solids)}")
    print(f"Result valid: {result_shape.isValid()}")

    if len(result_solids) != 1:
        raise ValueError(f"Boolean union did not produce one body; found {len(result_solids)} solids")

    return cq.Workplane(obj=result_shape)