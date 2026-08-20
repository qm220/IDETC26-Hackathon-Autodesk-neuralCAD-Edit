def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    root = model.val()
    solids = list(root.Solids())

    if len(solids) < 2:
        raise ValueError(f"Expected at least two solids, found {len(solids)}")

    # The smaller, central solid is the splined hub. Its front is the +Y side.
    hub_index = min(range(len(solids)), key=lambda i: solids[i].BoundingBox().xlen * solids[i].BoundingBox().zlen)
    hub = solids[hub_index]
    bb = hub.BoundingBox()

    front_y = bb.ymax
    outer_radius = max(abs(bb.xmin), abs(bb.xmax), abs(bb.zmin), abs(bb.zmax))
    chamfer_size = 1.0

    # Replace the rounded front-center perimeter treatment with an equal-distance
    # 1 mm chamfer.
    chamfer_start_y = front_y - chamfer_size
    front_radius = outer_radius - chamfer_size

    extension = 0.5
    cutter_height = chamfer_size + extension
    cutter_outer_radius = outer_radius + 4.0
    extended_end_radius = front_radius - extension

    outer_cylinder = cq.Solid.makeCylinder(
        cutter_outer_radius,
        cutter_height,
        cq.Vector(0, chamfer_start_y, 0),
        cq.Vector(0, 1, 0)
    )
    retained_cone = cq.Solid.makeCone(
        outer_radius,
        extended_end_radius,
        cutter_height,
        cq.Vector(0, chamfer_start_y, 0),
        cq.Vector(0, 1, 0)
    )
    chamfer_cutter = outer_cylinder.cut(retained_cone)
    edited_hub = hub.cut(chamfer_cutter)

    if not edited_hub.isValid():
        raise ValueError("The front-center chamfer operation produced an invalid hub")

    output_solids = [edited_hub if i == hub_index else solid for i, solid in enumerate(solids)]
    result_shape = cq.Compound.makeCompound(output_solids)
    return cq.Workplane("XY").newObject([result_shape])