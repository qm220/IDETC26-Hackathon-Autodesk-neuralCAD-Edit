def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported

    solids = list(root.Solids())
    faces = list(root.Faces())

    if len(solids) <= 55:
        raise ValueError(f"Expected lever solid 55, but only {len(solids)} solids were found")
    if len(faces) <= 529:
        raise ValueError(f"Expected lever faces 528/529, but only {len(faces)} faces were found")

    grip_face = faces[528]
    distal_face = faces[529]
    grip_bb = grip_face.BoundingBox()
    distal_center = distal_face.Center()

    spans = [grip_bb.xlen, grip_bb.ylen, grip_bb.zlen]
    axis_index = max(range(3), key=lambda i: spans[i])

    grip_center = grip_bb.center
    distal_values = [distal_center.x, distal_center.y, distal_center.z]
    grip_values = [grip_center.x, grip_center.y, grip_center.z]
    axis_sign = 1.0 if distal_values[axis_index] >= grip_values[axis_index] else -1.0

    direction_components = [0.0, 0.0, 0.0]
    direction_components[axis_index] = axis_sign
    direction = cq.Vector(*direction_components)

    transverse_spans = [spans[i] for i in range(3) if i != axis_index]
    radius = 0.25 * (transverse_spans[0] + transverse_spans[1])

    overlap = 0.05
    start = distal_center - direction.multiply(overlap)
    extension = cq.Solid.makeCylinder(radius, 50.0 + overlap, start, direction)

    extended_lever = solids[55].fuse(extension)
    if not extended_lever.isValid():
        raise ValueError("Extended lever solid is invalid")

    output_solids = [extended_lever if i == 55 else solid for i, solid in enumerate(solids)]
    result = cq.Compound.makeCompound(output_solids)

    if not result.isValid():
        raise ValueError("Final assembly is invalid")

    return result