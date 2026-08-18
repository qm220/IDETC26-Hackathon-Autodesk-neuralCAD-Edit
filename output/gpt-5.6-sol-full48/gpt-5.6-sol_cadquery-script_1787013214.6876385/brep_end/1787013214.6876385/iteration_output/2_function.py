def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()
    solids = list(shape.Solids())

    cartridge_index = None
    handle_index = None
    for i, solid in enumerate(solids):
        bb = solid.BoundingBox()
        vol = solid.Volume()
        dx, dy, dz = bb.xlen, bb.ylen, bb.zlen

        if (115.0 < dx < 130.0 and 130.0 < dy < 150.0 and
                115.0 < dz < 135.0 and 80000.0 < vol < 130000.0):
            cartridge_index = i

        if (18.0 < dx < 23.0 and 85.0 < dy < 100.0 and
                35.0 < dz < 45.0 and 30000.0 < vol < 50000.0):
            handle_index = i

    if cartridge_index is None or handle_index is None:
        raise ValueError(
            "Could not identify SEC-04 cartridge and handle: "
            f"cartridge={cartridge_index}, handle={handle_index}"
        )

    cartridge = solids[cartridge_index]
    old_handle = solids[handle_index]
    old_common = old_handle.intersect(cartridge)
    old_common_volume = old_common.Volume() if old_common is not None else 0.0

    hb = old_handle.BoundingBox()
    print(f"Cartridge solid index: {cartridge_index}")
    print(f"Handle solid index: {handle_index}")
    print(f"Original handle/cartridge common volume: {old_common_volume:.6f} mm^3")

    split_z = 106.680
    raise_amount = 4.000
    margin = 300.0

    lower_clip = cq.Solid.makeBox(
        hb.xlen + 2.0 * margin,
        hb.ylen + 2.0 * margin,
        split_z - (hb.zmin - margin),
        cq.Vector(hb.xmin - margin, hb.ymin - margin, hb.zmin - margin)
    )
    upper_clip = cq.Solid.makeBox(
        hb.xlen + 2.0 * margin,
        hb.ylen + 2.0 * margin,
        hb.zmax + margin - split_z,
        cq.Vector(hb.xmin - margin, hb.ymin - margin, split_z)
    )

    fixed_feet_and_legs = old_handle.intersect(lower_clip)
    raised_bridge = old_handle.intersect(upper_clip).translate(
        cq.Vector(0.0, 0.0, raise_amount)
    )

    left_leg_extension = cq.Solid.makeBox(
        hb.xlen,
        63.500 - hb.ymin,
        raise_amount,
        cq.Vector(hb.xmin, hb.ymin, split_z)
    )
    right_leg_extension = cq.Solid.makeBox(
        hb.xlen,
        hb.ymax - 124.460,
        raise_amount,
        cq.Vector(hb.xmin, 124.460, split_z)
    )

    revised_handle = fixed_feet_and_legs.fuse(left_leg_extension)
    revised_handle = revised_handle.fuse(right_leg_extension)
    revised_handle = revised_handle.fuse(raised_bridge)
    revised_handle = revised_handle.cut(cartridge).clean()

    revised_common = revised_handle.intersect(cartridge)
    revised_common_volume = revised_common.Volume() if revised_common is not None else 0.0
    print(f"Bridge raise amount: {raise_amount:.3f} mm")
    print(f"Revised handle/cartridge common volume: {revised_common_volume:.9f} mm^3")
    print(f"Revised handle valid: {revised_handle.isValid()}")

    if revised_common_volume > 1.0e-5:
        raise ValueError(
            f"Handle/coffeepot interference remains: {revised_common_volume:.9f} mm^3"
        )
    if not revised_handle.isValid():
        raise ValueError("Revised handle is invalid")

    output_solids = [solid for i, solid in enumerate(solids) if i != handle_index]
    output_solids.extend(revised_handle.Solids())
    result = cq.Compound.makeCompound(output_solids)
    return cq.Workplane(obj=result)