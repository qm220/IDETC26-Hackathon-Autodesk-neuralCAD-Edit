def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported
    solids = list(root.Solids())

    if len(solids) <= 8:
        raise ValueError(f"Expected solid 8 (Nozzle Volcano), but STEP contains only {len(solids)} solids")

    # The supplied model plan explicitly identifies solid 8 as the long,
    # high-reach Volcano nozzle.
    target_index = 8
    target = solids[target_index]
    bb = target.BoundingBox()
    lengths = [bb.xlen, bb.ylen, bb.zlen]
    axis_index = max(range(3), key=lambda i: lengths[i])
    axis_name = ("X", "Y", "Z")[axis_index]

    mins = [bb.xmin, bb.ymin, bb.zmin]
    maxs = [bb.xmax, bb.ymax, bb.zmax]
    original_height = maxs[axis_index] - mins[axis_index]
    reduction = 1.0

    if original_height <= reduction:
        raise ValueError(f"Nozzle axial height {original_height:.6f} mm is too small to shorten by 1 mm")

    margin = max(2.0, max(lengths) * 0.1)

    def make_global_box(bounds_min, bounds_max):
        dx = bounds_max[0] - bounds_min[0]
        dy = bounds_max[1] - bounds_min[1]
        dz = bounds_max[2] - bounds_min[2]
        return cq.Solid.makeBox(dx, dy, dz, cq.Vector(*bounds_min))

    # Compare material contained near both axial ends. The threaded free end
    # has a substantially larger annular section than the small nozzle outlet
    # at the conical tip, allowing the threaded end to be selected without
    # relying on a particular global axis direction.
    sample_depth = min(0.8, original_height * 0.1)
    expanded_min = [bb.xmin - margin, bb.ymin - margin, bb.zmin - margin]
    expanded_max = [bb.xmax + margin, bb.ymax + margin, bb.zmax + margin]

    low_min = list(expanded_min)
    low_max = list(expanded_max)
    low_min[axis_index] = mins[axis_index] - 0.01
    low_max[axis_index] = mins[axis_index] + sample_depth

    high_min = list(expanded_min)
    high_max = list(expanded_max)
    high_min[axis_index] = maxs[axis_index] - sample_depth
    high_max[axis_index] = maxs[axis_index] + 0.01

    low_sample = target.intersect(make_global_box(low_min, low_max))
    high_sample = target.intersect(make_global_box(high_min, high_max))
    low_volume = low_sample.Volume() if not low_sample.isNull() else 0.0
    high_volume = high_sample.Volume() if not high_sample.isNull() else 0.0
    trim_high_end = high_volume >= low_volume

    # Intersect with a retaining half-space represented by an oversized box.
    # This removes exactly 1 mm from the selected threaded terminal end and
    # simultaneously trims the external thread and coaxial internal passage.
    retain_min = list(expanded_min)
    retain_max = list(expanded_max)
    if trim_high_end:
        retain_min[axis_index] = mins[axis_index] - margin
        retain_max[axis_index] = maxs[axis_index] - reduction
        trimmed_end = "maximum"
    else:
        retain_min[axis_index] = mins[axis_index] + reduction
        retain_max[axis_index] = maxs[axis_index] + margin
        trimmed_end = "minimum"

    retaining_box = make_global_box(retain_min, retain_max)
    modified = target.intersect(retaining_box)
    modified_solids = list(modified.Solids())

    if len(modified_solids) != 1:
        raise ValueError(f"Volcano nozzle trim produced {len(modified_solids)} solids instead of one")

    modified_nozzle = modified_solids[0]
    if not modified_nozzle.isValid():
        raise ValueError("The shortened Volcano nozzle is not a valid solid")

    new_bb = modified_nozzle.BoundingBox()
    new_lengths = [new_bb.xlen, new_bb.ylen, new_bb.zlen]
    new_height = new_lengths[axis_index]
    actual_reduction = original_height - new_height

    if abs(actual_reduction - reduction) > 1.0e-5:
        raise ValueError(
            f"Expected a 1.000000 mm reduction, obtained {actual_reduction:.6f} mm"
        )

    # Replace only solid 8. All surrounding hotend and mounting components are
    # retained as their original, separate B-rep solids.
    output_solids = list(solids)
    output_solids[target_index] = modified_nozzle
    result = cq.Compound.makeCompound(output_solids)

    print(f"Loaded {len(solids)} solids")
    print(f"Edited solid {target_index}: long high-reach Nozzle Volcano")
    print(f"Detected nozzle axis: {axis_name}")
    print(f"End sample volumes: low={low_volume:.6f}, high={high_volume:.6f} mm^3")
    print(f"Trimmed threaded end at the {trimmed_end} {axis_name} extent")
    print(f"Original axial height: {original_height:.6f} mm")
    print(f"New axial height: {new_height:.6f} mm")
    print(f"Axial reduction: {actual_reduction:.6f} mm")
    print(f"Result valid: {result.isValid()}")

    return result