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

    # Replace the existing rounded/beveled front-center perimeter treatment with
    # an equal-distance 1 mm chamfer. The retained boundary decreases by 1 mm
    # in radius over the final 1 mm toward the +Y front face.
    chamfer_start_y = front_y - chamfer_size
    front_radius = outer_radius - chamfer_size

    # Construct an oversized annular cutter. The inner conical boundary is the
    # desired chamfer surface; extending it beyond the front avoids coincident
    # boolean faces at the original front plane.
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

    output_solids = []
    for i, solid in enumerate(solids):
        output_solids.append(edited_hub if i == hub_index else solid)

    result_shape = cq.Compound.makeCompound(output_solids)
    result = cq.Workplane("XY").newObject([result_shape])

    print(f"Edited hub solid index: {hub_index}")
    print(f"Hub front Y: {front_y:.4f} mm")
    print(f"Chamfer start Y: {chamfer_start_y:.4f} mm")
    print(f"Hub outer radius: {outer_radius:.4f} mm")
    print(f"Front radius after chamfer: {front_radius:.4f} mm")
    print(f"Applied equal-distance front-center chamfer: {chamfer_size:.4f} mm")
    print(f"Result valid: {result_shape.isValid()}")
    print(f"Result solids: {len(result_shape.Solids())}")

    return result