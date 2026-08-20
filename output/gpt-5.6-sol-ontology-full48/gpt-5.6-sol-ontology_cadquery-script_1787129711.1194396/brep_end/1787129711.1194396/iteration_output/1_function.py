def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported

    print(f"Loaded STEP: {input_file}")
    print(f"Valid before edit: {root.isValid()}")
    print(f"Initial solids: {len(root.Solids())}, faces: {len(root.Faces())}")
    print(f"Initial volume: {root.Volume():.6f} mm^3")

    faces = root.Faces()
    for face_index in (64, 67, 103, 106):
        if face_index < len(faces):
            face = faces[face_index]
            c = face.Center()
            bb = face.BoundingBox()
            print(
                f"FACE {face_index}: center=({c.x:.6f}, {c.y:.6f}, {c.z:.6f}), "
                f"bbox=({bb.xmin:.6f},{bb.ymin:.6f},{bb.zmin:.6f}) to "
                f"({bb.xmax:.6f},{bb.ymax:.6f},{bb.zmax:.6f}), "
                f"area={face.Area():.6f}"
            )

    solids = list(root.Solids())
    platform_indices = []
    for i, solid in enumerate(solids):
        bb = solid.BoundingBox()
        if bb.xlen > 95.0 and 10.0 < bb.ylen < 14.0 and bb.zlen > 40.0:
            platform_indices.append(i)

    if len(platform_indices) != 2:
        raise ValueError(
            f"Expected two platform solids but localized {len(platform_indices)}: "
            f"{platform_indices}"
        )

    hole_radius = 2.5
    x_centers = (-10.0, 2.0, 14.0, 26.0)
    z_centers = (-10.0, 10.0)

    edited_solids = []
    removed_volume = 0.0
    for i, solid in enumerate(solids):
        if i not in platform_indices:
            edited_solids.append(solid)
            continue

        bb = solid.BoundingBox()
        before = solid.Volume()
        edited = solid
        cutter_start_y = bb.ymin - 1.0
        cutter_length = bb.ylen + 2.0

        for x in x_centers:
            for z in z_centers:
                cutter = cq.Solid.makeCylinder(
                    hole_radius,
                    cutter_length,
                    cq.Vector(x, cutter_start_y, z),
                    cq.Vector(0.0, 1.0, 0.0)
                )
                edited = edited.cut(cutter)

        if not edited.isValid():
            raise ValueError(f"Edited platform solid {i} is invalid")

        after = edited.Volume()
        removed_volume += before - after
        edited_solids.append(edited)

    result = cq.Compound.makeCompound(edited_solids)
    print(f"Localized platform solid indices: {platform_indices}")
    print(f"Total new holes: {len(platform_indices) * len(x_centers) * len(z_centers)}")
    print(f"Removed platform volume: {removed_volume:.6f} mm^3")
    print(f"Final solids: {len(result.Solids())}, faces: {len(result.Faces())}")
    print(f"Final volume: {result.Volume():.6f} mm^3")
    print(f"Valid after edit: {result.isValid()}")
    return result