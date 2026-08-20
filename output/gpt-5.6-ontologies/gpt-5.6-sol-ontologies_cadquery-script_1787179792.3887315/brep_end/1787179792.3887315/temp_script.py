def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    if not shape.isValid():
        raise RuntimeError("Imported STEP model is not a valid shape")

    bb = shape.BoundingBox()
    x_cut = 100.0
    z_mid = 0.5 * (bb.zmin + bb.zmax)
    margin = max(bb.xlen, bb.ylen, bb.zlen) + 20.0

    print("BOUNDING BOX:", bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax)
    print("LARGE-END X CUT:", x_cut)
    print("THICKNESS MIRROR PLANE Z:", z_mid)

    # The enlarged end already has the required radii on its lower-Z side.
    # Mirror that existing geometry about the mid-thickness plane, then retain
    # only material common to the original and mirrored shapes. This transfers
    # the exact existing radii to the opposite (upper-Z) side, including the
    # different radius values around the enlarged end.
    mirrored = shape.mirror(
        mirrorPlane="XY",
        basePointVector=(0.0, 0.0, z_mid)
    )

    # Restrict the symmetry operation to the visually enlarged end (X <= 100).
    left_clip = cq.Solid.makeBox(
        (x_cut - bb.xmin) + margin,
        bb.ylen + 2.0 * margin,
        bb.zlen + 2.0 * margin,
        cq.Vector(bb.xmin - margin, bb.ymin - margin, bb.zmin - margin)
    )
    right_clip = cq.Solid.makeBox(
        (bb.xmax - x_cut) + margin,
        bb.ylen + 2.0 * margin,
        bb.zlen + 2.0 * margin,
        cq.Vector(x_cut, bb.ymin - margin, bb.zmin - margin)
    )

    original_large_end = shape.intersect(left_clip)
    mirrored_large_end = mirrored.intersect(left_clip)
    radiused_large_end = original_large_end.intersect(mirrored_large_end)

    # Preserve all geometry outside the enlarged end exactly as imported.
    preserved_remainder = shape.intersect(right_clip)
    edited = radiused_large_end.fuse(preserved_remainder).clean()

    print("ORIGINAL VALID:", shape.isValid())
    print("RESULT VALID:", edited.isValid())
    print("ORIGINAL VOLUME:", shape.Volume())
    print("RESULT VOLUME:", edited.Volume())
    print("REMOVED VOLUME:", shape.Volume() - edited.Volume())
    print("ORIGINAL/RESULT FACES:", len(shape.Faces()), len(edited.Faces()))
    print("RESULT SOLIDS:", len(edited.Solids()))

    if not edited.isValid():
        raise RuntimeError("The mirrored-radius result is not a valid solid")
    if len(edited.Solids()) != 1:
        raise RuntimeError("The edit did not produce one connected solid")
    if edited.Volume() >= shape.Volume() - 1.0e-6:
        raise RuntimeError("No material was removed while transferring the opposite-side radii")

    return cq.Workplane("XY").newObject([edited])