def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported
    solids = list(root.Solids())

    print(f"Loaded STEP: {input_file}")
    print(f"Detected solids: {len(solids)}")

    if len(solids) <= 8:
        raise ValueError(f"Expected SOLID 8, but STEP contains only {len(solids)} solids")

    # SOLID 8 is the long Volcano nozzle fitting. Its extrusion axis is Z.
    target_index = 8
    target = solids[target_index]
    bb = target.BoundingBox()
    original_height = bb.zlen

    # Remove one complete 1 mm thread-pitch band from within the threaded area.
    # Preserve the terminal end geometry by translating everything above the
    # removed band downward, rather than trimming the terminal end itself.
    reduction = 1.0
    band_z0 = 19.0
    band_z1 = band_z0 + reduction

    if band_z0 <= bb.zmin or band_z1 >= bb.zmax:
        raise ValueError("Selected shortening band is outside the target solid")

    margin = max(bb.xlen, bb.ylen, bb.zlen, 1.0) + 10.0

    lower_box = cq.Solid.makeBox(
        bb.xlen + 2.0 * margin,
        bb.ylen + 2.0 * margin,
        band_z0 - bb.zmin + margin,
        cq.Vector(bb.xmin - margin, bb.ymin - margin, bb.zmin - margin)
    )
    upper_box = cq.Solid.makeBox(
        bb.xlen + 2.0 * margin,
        bb.ylen + 2.0 * margin,
        bb.zmax - band_z1 + margin,
        cq.Vector(bb.xmin - margin, bb.ymin - margin, band_z1)
    )

    lower = target.intersect(lower_box)
    upper = target.intersect(upper_box)

    if lower.isNull() or upper.isNull():
        raise ValueError("Failed to split the Volcano nozzle around the threaded band")

    upper_shifted = upper.moved(cq.Location(cq.Vector(0, 0, -reduction)))
    shortened = lower.fuse(upper_shifted).clean()

    if shortened.isNull() or not shortened.isValid():
        raise ValueError("Thread-band shortening produced invalid geometry")

    shortened_solids = list(shortened.Solids())
    if len(shortened_solids) != 1:
        raise ValueError(
            f"Shortened Volcano nozzle did not merge into one solid; got {len(shortened_solids)} solids"
        )

    shortened = shortened_solids[0]
    new_bb = shortened.BoundingBox()
    actual_reduction = original_height - new_bb.zlen

    print(
        f"SOLID 8 original Z range: [{bb.zmin:.6f}, {bb.zmax:.6f}], "
        f"height={original_height:.6f}"
    )
    print(
        f"Removed threaded band: Z=[{band_z0:.6f}, {band_z1:.6f}] "
        f"and translated preserved upper end by {-reduction:.6f} mm"
    )
    print(
        f"SOLID 8 final Z range: [{new_bb.zmin:.6f}, {new_bb.zmax:.6f}], "
        f"height={new_bb.zlen:.6f}, reduction={actual_reduction:.6f}"
    )

    if abs(actual_reduction - reduction) > 1.0e-5:
        raise ValueError(
            f"Expected exactly 1.0 mm overall-height reduction, got {actual_reduction:.6f} mm"
        )

    # Preserve every other assembly body exactly.
    result_solids = [shortened if i == target_index else solid for i, solid in enumerate(solids)]
    result = cq.Compound.makeCompound(result_solids)

    print(f"Result contains {len(result.Solids())} solids; valid={result.isValid()}")
    return result