def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported
    solids = list(root.Solids())

    if len(solids) <= 8:
        raise ValueError(f"Expected solid 8 (Nozzle Volcano), but STEP contains only {len(solids)} solids")

    target_index = 8
    target = solids[target_index]
    bb = target.BoundingBox()
    lengths = [bb.xlen, bb.ylen, bb.zlen]
    axis_index = max(range(3), key=lambda i: lengths[i])

    mins = [bb.xmin, bb.ymin, bb.zmin]
    maxs = [bb.xmax, bb.ymax, bb.zmax]
    original_height = maxs[axis_index] - mins[axis_index]
    reduction = 1.0

    if original_height <= reduction:
        raise ValueError("Nozzle is too short for the requested reduction")

    margin = max(2.0, max(lengths) * 0.1)

    def make_box(bounds_min, bounds_max):
        return cq.Solid.makeBox(
            bounds_max[0] - bounds_min[0],
            bounds_max[1] - bounds_min[1],
            bounds_max[2] - bounds_min[2],
            cq.Vector(*bounds_min)
        )

    sample_depth = min(0.8, original_height * 0.1)
    expanded_min = [bb.xmin - margin, bb.ymin - margin, bb.zmin - margin]
    expanded_max = [bb.xmax + margin, bb.ymax + margin, bb.zmax + margin]

    low_min, low_max = list(expanded_min), list(expanded_max)
    low_min[axis_index] = mins[axis_index] - 0.01
    low_max[axis_index] = mins[axis_index] + sample_depth

    high_min, high_max = list(expanded_min), list(expanded_max)
    high_min[axis_index] = maxs[axis_index] - sample_depth
    high_max[axis_index] = maxs[axis_index] + 0.01

    low_sample = target.intersect(make_box(low_min, low_max))
    high_sample = target.intersect(make_box(high_min, high_max))
    low_volume = low_sample.Volume() if not low_sample.isNull() else 0.0
    high_volume = high_sample.Volume() if not high_sample.isNull() else 0.0
    trim_high_end = high_volume >= low_volume

    retain_min, retain_max = list(expanded_min), list(expanded_max)
    if trim_high_end:
        retain_max[axis_index] = maxs[axis_index] - reduction
    else:
        retain_min[axis_index] = mins[axis_index] + reduction

    modified = target.intersect(make_box(retain_min, retain_max))
    modified_solids = list(modified.Solids())
    if len(modified_solids) != 1:
        raise ValueError(f"Nozzle trim produced {len(modified_solids)} solids instead of one")

    modified_nozzle = modified_solids[0]
    if not modified_nozzle.isValid():
        raise ValueError("Shortened nozzle is not a valid solid")

    output_solids = list(solids)
    output_solids[target_index] = modified_nozzle
    return cq.Compound.makeCompound(output_solids)