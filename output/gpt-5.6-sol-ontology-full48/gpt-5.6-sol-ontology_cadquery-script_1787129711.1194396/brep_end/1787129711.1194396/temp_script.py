def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported

    print(f"Loaded STEP: {input_file}")
    print(f"Valid before edit: {root.isValid()}")
    print(f"Initial solids: {len(root.Solids())}, faces: {len(root.Faces())}")
    print(f"Initial volume: {root.Volume():.6f} mm^3")

    # Bind selected planning FACE indices to the imported STEP geometry and
    # report their measured locations before editing.
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
    for i, solid in enumerate(solids):
        bb = solid.BoundingBox()
        c = bb.center
        print(
            f"Solid {i}: center=({c.x:.6f},{c.y:.6f},{c.z:.6f}), "
            f"size=({bb.xlen:.6f},{bb.ylen:.6f},{bb.zlen:.6f}), "
            f"volume={solid.Volume():.6f}"
        )

    # Locate only the two platform solids by their characteristic dimensions:
    # approximately 100 mm in X, 12 mm in Y, and 45 mm in Z.
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

    # Eight cylindrical through-holes per platform: four X columns and two Z rows.
    # This central/right-side layout remains clear of the left guide slot,
    # the fixed pivot bore near x=42.743, and the platform perimeter.
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

        # Start below the negative-Y platform face and cut along +Y beyond the
        # positive-Y face, ensuring a true through-all result despite tolerance.
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
        print(
            f"Edited platform solid {i}: y=[{bb.ymin:.6f},{bb.ymax:.6f}], "
            f"8 holes diameter={2.0 * hole_radius:.3f} mm, "
            f"volume {before:.6f} -> {after:.6f} mm^3"
        )
        edited_solids.append(edited)

    result = cq.Compound.makeCompound(edited_solids)
    print(f"Localized platform solid indices: {platform_indices}")
    print(f"Total new holes: {len(platform_indices) * len(x_centers) * len(z_centers)}")
    print(f"Removed platform volume: {removed_volume:.6f} mm^3")
    print(f"Final solids: {len(result.Solids())}, faces: {len(result.Faces())}")
    print(f"Final volume: {result.Volume():.6f} mm^3")
    print(f"Valid after edit: {result.isValid()}")
    return result