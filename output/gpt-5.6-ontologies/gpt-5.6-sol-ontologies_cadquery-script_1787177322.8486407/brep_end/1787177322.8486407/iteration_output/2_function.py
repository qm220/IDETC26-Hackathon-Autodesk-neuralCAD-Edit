def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()
    solids = list(shape.Solids())

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

    extension = cq.Solid.makeCylinder(
        14.62,
        50.0,
        cq.Vector(-149.0, 202.0, old_bb.zmax),
        cq.Vector(0.0, 0.0, 1.0),
    )
    extended_lever = lever.fuse(extension)

    output_solids = [extended_lever if i == target_index else s for i, s in enumerate(solids)]
    result = cq.Compound.makeCompound(output_solids)
    return cq.Workplane("XY").newObject([result])