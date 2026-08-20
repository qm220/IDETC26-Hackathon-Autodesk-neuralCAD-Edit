def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()
    solids = list(shape.Solids())

    # The operating lever is the isolated, Z-oriented shaft identified as
    # SOLID 55 / feature F008. Its attachment is at Z=292 mm and its free end
    # is at Z=432 mm. Extend only the free cylindrical end by 50 mm (5 cm).
    target_index = None
    for i, solid in enumerate(solids):
        bb = solid.BoundingBox()
        c = solid.Center()
        if (
            28.0 < bb.xlen < 31.0
            and 28.0 < bb.ylen < 31.0
            and 139.0 < bb.zlen < 141.0
            and abs(c.x + 149.0) < 1.0
            and abs(c.y - 202.0) < 1.0
            and abs(bb.zmax - 432.0) < 1.0
        ):
            target_index = i
            break

    if target_index is None:
        raise ValueError("Could not uniquely locate the forward-projecting operating lever")

    lever = solids[target_index]
    old_bb = lever.BoundingBox()

    # Continue the existing main grip cylinder from its free end. The existing
    # cylindrical grip has radius 14.62 mm and axis +Z.
    extension_length = 50.0
    grip_radius = 14.62
    extension = cq.Solid.makeCylinder(
        grip_radius,
        extension_length,
        cq.Vector(-149.0, 202.0, old_bb.zmax),
        cq.Vector(0.0, 0.0, 1.0),
    )
    extended_lever = lever.fuse(extension)

    # Replace only the lever solid; preserve every other imported solid exactly.
    output_solids = [extended_lever if i == target_index else s for i, s in enumerate(solids)]
    result = cq.Compound.makeCompound(output_solids)

    new_bb = extended_lever.BoundingBox()
    print(f"Extended SOLID {target_index} operating lever")
    print(f"Original free end Z: {old_bb.zmax:.4f} mm")
    print(f"New free end Z: {new_bb.zmax:.4f} mm")
    print(f"Length increase: {new_bb.zmax - old_bb.zmax:.4f} mm")
    print(f"Result valid: {result.isValid()}")
    print(f"Result solids: {len(result.Solids())}")

    return cq.Workplane("XY").newObject([result])