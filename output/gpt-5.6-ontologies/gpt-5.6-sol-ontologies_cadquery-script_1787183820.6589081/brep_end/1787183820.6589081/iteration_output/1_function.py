def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    solids = list(shape.Solids())
    model_bb = shape.BoundingBox()

    # Identify the four long, Z-oriented pivot pins by their slender cylindrical
    # envelopes. This excludes the two short center pins and preserves all arms,
    # platforms, slots, and bores unchanged.
    long_pin_indices = []
    for i, solid in enumerate(solids):
        bb = solid.BoundingBox()
        if (
            bb.zlen > 0.80 * model_bb.zlen
            and bb.xlen < 0.12 * model_bb.xlen
            and bb.ylen < 0.12 * model_bb.ylen
            and len(solid.Faces()) <= 6
        ):
            long_pin_indices.append(i)

    if len(long_pin_indices) != 4:
        raise ValueError(
            "Expected four long pivot pins, but identified "
            f"{len(long_pin_indices)} at solid indices {long_pin_indices}"
        )

    # The existing long pins are 4.8 mm in diameter. A 7.2 mm diameter head
    # gives 1.2 mm radial retention beyond the pin, while a 1.5 mm thickness
    # keeps the change compact. Heads are fitted to both exposed ends because
    # both linkage layers require axial retention.
    head_radius = 3.6
    head_thickness = 1.5
    join_overlap = 0.10

    edited_solids = []
    added_head_count = 0

    for i, solid in enumerate(solids):
        if i not in long_pin_indices:
            edited_solids.append(solid)
            continue

        bb = solid.BoundingBox()
        center = solid.Center()

        lower_head = cq.Solid.makeCylinder(
            head_radius,
            head_thickness + join_overlap,
            cq.Vector(center.x, center.y, bb.zmin - head_thickness),
            cq.Vector(0, 0, 1),
        )
        upper_head = cq.Solid.makeCylinder(
            head_radius,
            head_thickness + join_overlap,
            cq.Vector(center.x, center.y, bb.zmax - join_overlap),
            cq.Vector(0, 0, 1),
        )

        headed_pin = solid.fuse(lower_head, upper_head)
        if not headed_pin.isValid():
            raise ValueError(f"Headed long pin at solid index {i} is invalid")

        edited_solids.append(headed_pin)
        added_head_count += 2

        print(
            f"Headed long pin SOLID {i}: axis=({center.x:.4f}, {center.y:.4f}), "
            f"original z=({bb.zmin:.4f}, {bb.zmax:.4f})"
        )

    result_shape = cq.Compound.makeCompound(edited_solids)
    print(f"Long pins modified: {len(long_pin_indices)}")
    print(f"Cylindrical retaining heads added: {added_head_count}")
    print(f"Result valid: {result_shape.isValid()}")
    print(f"Result solids: {len(result_shape.Solids())}")

    return cq.Workplane("XY").newObject([result_shape])