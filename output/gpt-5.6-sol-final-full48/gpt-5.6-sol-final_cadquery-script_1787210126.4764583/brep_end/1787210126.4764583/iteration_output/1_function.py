def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported
    solids = list(root.Solids())

    if len(solids) < 2:
        raise ValueError("The input model does not contain enough solids for two platforms")

    ranked = sorted(solids, key=lambda s: s.Volume(), reverse=True)
    platform_candidates = []
    for solid in ranked:
        bb = solid.BoundingBox()
        dx = bb.xmax - bb.xmin
        dy = bb.ymax - bb.ymin
        dz = bb.zmax - bb.zmin
        if dx > 2.0 * dy and dz > 1.5 * dy:
            platform_candidates.append(solid)
        if len(platform_candidates) == 2:
            break

    if len(platform_candidates) != 2:
        platform_candidates = ranked[:2]

    platform_ids = {id(s) for s in platform_candidates}
    modified_platforms = []

    for platform_index, platform in enumerate(platform_candidates):
        bb = platform.BoundingBox()
        length_x = bb.xmax - bb.xmin
        thickness_y = bb.ymax - bb.ymin
        depth_z = bb.zmax - bb.zmin
        cx = 0.5 * (bb.xmin + bb.xmax)
        cz = 0.5 * (bb.zmin + bb.zmax)

        diameter = min(0.060 * length_x, 0.13 * depth_z)
        diameter = max(diameter, 2.0)
        radius = 0.5 * diameter

        x_fracs = (-0.08, 0.04, 0.16, 0.28)
        z_fracs = (-0.27, 0.0, 0.27)
        row_stagger = 0.03 * length_x

        result = platform
        accepted = 0
        for row, zf in enumerate(z_fracs):
            stagger = row_stagger if row == 1 else 0.0
            for xf in x_fracs:
                x = cx + xf * length_x + stagger
                z = cz + zf * depth_z

                if x - radius <= bb.xmin + 0.05 * length_x:
                    continue
                if x + radius >= bb.xmax - 0.08 * length_x:
                    continue
                if z - radius <= bb.zmin + 0.10 * depth_z:
                    continue
                if z + radius >= bb.zmax - 0.10 * depth_z:
                    continue

                cutter = cq.Solid.makeCylinder(
                    radius,
                    thickness_y + 4.0,
                    cq.Vector(x, bb.ymin - 2.0, z),
                    cq.Vector(0, 1, 0)
                )
                candidate = result.cut(cutter)
                if candidate.isValid() and len(candidate.Solids()) == 1:
                    result = candidate
                    accepted += 1

        result = result.clean()
        if not result.isValid() or len(result.Solids()) != 1:
            raise ValueError("A platform became invalid during hole cutting")

        print(
            "Platform %d: cut %d cylindrical through-holes, diameter %.3f mm"
            % (platform_index + 1, accepted, diameter)
        )
        modified_platforms.append(result)

    output_solids = []
    replacement_index = 0
    for solid in solids:
        if id(solid) in platform_ids:
            output_solids.append(modified_platforms[replacement_index])
            replacement_index += 1
        else:
            output_solids.append(solid)

    result = cq.Compound.makeCompound(output_solids)
    print("Preserved %d original non-platform solids" % (len(solids) - 2))
    print("Final assembly solids: %d; valid: %s" % (len(result.Solids()), result.isValid()))
    return result