def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()
    solids = list(shape.Solids())

    long_pin_indices = []
    for i, solid in enumerate(solids):
        bb = solid.BoundingBox()
        if bb.zlen > 45.0 and bb.xlen < 7.0 and bb.ylen < 7.0:
            long_pin_indices.append(i)

    print(f"Detected long platform pins: {len(long_pin_indices)} at solid indices {long_pin_indices}")
    if len(long_pin_indices) != 4:
        raise ValueError(f"Expected four long z-directed platform pins, detected {len(long_pin_indices)}")

    head_radius = 3.60
    head_thickness = 1.50
    outer_chamfer = 0.30

    output_solids = []
    for i, solid in enumerate(solids):
        if i not in long_pin_indices:
            output_solids.append(solid)
            continue

        bb = solid.BoundingBox()
        cx = (bb.xmin + bb.xmax) * 0.5
        cy = (bb.ymin + bb.ymax) * 0.5
        zmin = bb.zmin
        zmax = bb.zmax

        pos_body = cq.Solid.makeCylinder(
            head_radius,
            head_thickness - outer_chamfer,
            cq.Vector(cx, cy, zmax),
            cq.Vector(0, 0, 1),
        )
        pos_rim = cq.Solid.makeCone(
            head_radius,
            head_radius - outer_chamfer,
            outer_chamfer,
            cq.Vector(cx, cy, zmax + head_thickness - outer_chamfer),
            cq.Vector(0, 0, 1),
        )

        neg_body = cq.Solid.makeCylinder(
            head_radius,
            head_thickness - outer_chamfer,
            cq.Vector(cx, cy, zmin),
            cq.Vector(0, 0, -1),
        )
        neg_rim = cq.Solid.makeCone(
            head_radius,
            head_radius - outer_chamfer,
            outer_chamfer,
            cq.Vector(cx, cy, zmin - head_thickness + outer_chamfer),
            cq.Vector(0, 0, -1),
        )

        retained_pin = solid.fuse(pos_body, pos_rim, neg_body, neg_rim)
        try:
            retained_pin = retained_pin.clean()
        except Exception:
            pass

        if not retained_pin.isValid():
            raise ValueError(f"Modified long pin at solid index {i} is invalid")

        output_solids.append(retained_pin)

    result_shape = cq.Compound.makeCompound(output_solids)
    print(f"Result valid: {result_shape.isValid()}")
    print(f"Result solid count: {len(result_shape.Solids())}")
    print("Added eight cylindrical retaining heads: two on each of four long platform pins.")

    return cq.Workplane(obj=result_shape)