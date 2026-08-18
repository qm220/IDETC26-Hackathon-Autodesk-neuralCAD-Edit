def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported

    solids = list(root.Solids())
    print(f"Imported {len(solids)} solids; valid={root.isValid()}")

    platform_indices = []
    for i, solid in enumerate(solids):
        bb = solid.BoundingBox()
        dx = bb.xmax - bb.xmin
        dy = bb.ymax - bb.ymin
        dz = bb.zmax - bb.zmin
        print(
            f"Solid {i}: size=({dx:.3f}, {dy:.3f}, {dz:.3f}), "
            f"center=({bb.center.x:.3f}, {bb.center.y:.3f}, {bb.center.z:.3f}), "
            f"volume={solid.Volume():.3f}"
        )
        # The two platforms are the only approximately 100 x 12 x 45 mm solids.
        if dx > 90.0 and 9.0 < dy < 15.0 and 38.0 < dz < 50.0:
            platform_indices.append(i)

    print(f"Detected platform solid indices: {platform_indices}")
    if len(platform_indices) != 2:
        raise ValueError(
            f"Expected exactly two platform solids, detected {len(platform_indices)}"
        )

    # Editor-selected symmetric 4 x 3 pattern: twelve 6 mm through-holes
    # per platform. The pattern is confined to the central region to preserve
    # both end pivot/slot bearing regions and the external edge ligaments.
    x_offsets = (-15.0, -5.0, 5.0, 15.0)
    z_offsets = (-12.0, 0.0, 12.0)
    hole_radius = 3.0

    output_solids = []
    for i, solid in enumerate(solids):
        if i not in platform_indices:
            output_solids.append(solid)
            continue

        bb = solid.BoundingBox()
        cx = 0.5 * (bb.xmin + bb.xmax)
        cz = 0.5 * (bb.zmin + bb.zmax)
        cut_shape = solid

        for xoff in x_offsets:
            for zoff in z_offsets:
                cutter = cq.Solid.makeCylinder(
                    hole_radius,
                    (bb.ymax - bb.ymin) + 4.0,
                    cq.Vector(cx + xoff, bb.ymin - 2.0, cz + zoff),
                    cq.Vector(0.0, 1.0, 0.0)
                )
                cut_shape = cut_shape.cut(cutter)

        if not cut_shape.isValid():
            raise ValueError(f"Edited platform solid {i} is invalid")

        removed = solid.Volume() - cut_shape.Volume()
        print(
            f"Platform {i}: added {len(x_offsets) * len(z_offsets)} holes, "
            f"removed volume={removed:.3f} mm^3 "
            f"({100.0 * removed / solid.Volume():.2f}%)"
        )
        output_solids.append(cut_shape)

    result = cq.Compound.makeCompound(output_solids)
    print(
        f"Edited assembly: solids={len(result.Solids())}, "
        f"valid={result.isValid()}, volume={result.Volume():.3f} mm^3"
    )
    return result