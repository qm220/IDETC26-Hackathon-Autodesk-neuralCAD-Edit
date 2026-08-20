def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported
    solids = list(root.Solids())

    if len(solids) < 8:
        raise ValueError("Expected the existing 12-solid scissor-lift assembly")

    shaft_indices = (1, 3, 6, 7)
    updated_solids = list(solids)

    for index in shaft_indices:
        shaft = solids[index]
        bb = shaft.BoundingBox()
        cx = 0.5 * (bb.xmin + bb.xmax)
        cy = 0.5 * (bb.ymin + bb.ymax)
        pin_diameter = min(bb.xlen, bb.ylen)

        head_diameter = 1.45 * pin_diameter
        head_radius = 0.5 * head_diameter
        head_thickness = max(0.22 * pin_diameter, 0.8)

        rear_head = cq.Solid.makeCylinder(
            head_radius,
            head_thickness,
            cq.Vector(cx, cy, bb.zmin),
            cq.Vector(0, 0, -1),
        )
        front_head = cq.Solid.makeCylinder(
            head_radius,
            head_thickness,
            cq.Vector(cx, cy, bb.zmax),
            cq.Vector(0, 0, 1),
        )

        updated_solids[index] = shaft.fuse(rear_head, front_head)

    return cq.Compound.makeCompound(updated_solids)