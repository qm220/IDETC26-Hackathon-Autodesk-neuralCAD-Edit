def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    model = imported.val() if hasattr(imported, "val") else imported

    print(f"Loaded STEP: {input_file}")
    print(f"Model valid: {model.isValid()}")
    print(f"Faces: {len(model.Faces())}, solids: {len(model.Solids())}")

    # Bind the planning-stage FACE N references to the loaded STEP geometry.
    referenced_faces = [30, 31, 33, 38, 39, 41, 121, 122, 124, 126, 127, 129]
    faces = model.Faces()
    for index in referenced_faces:
        if index < len(faces):
            face = faces[index]
            center = face.Center()
            bb = face.BoundingBox()
            try:
                geom_type = face.geomType()
            except Exception:
                geom_type = "unknown"
            print(
                f"FACE {index}: type={geom_type}, "
                f"center=({center.x:.6f}, {center.y:.6f}, {center.z:.6f}), "
                f"bbox=({bb.xmin:.6f},{bb.ymin:.6f},{bb.zmin:.6f}) to "
                f"({bb.xmax:.6f},{bb.ymax:.6f},{bb.zmax:.6f})"
            )

    # Four G003 long-pin axes. F021 and F022 are deliberately excluded.
    pin_axes = [
        (42.743402, 1.752975, "F017 lower-right"),
        (-37.303780, 1.752975, "F018 lower-left sliding"),
        (42.743402, 44.605773, "F019 upper-right"),
        (-37.303780, 44.605773, "F020 upper-left sliding"),
    ]

    solids = list(model.Solids())
    used_indices = set()
    replacements = {}

    # Selected retention geometry: 7 mm diameter exceeds both the 4.8 mm
    # shaft and 5.0 mm link bores. A 2 mm head thickness is used at each end.
    head_radius = 3.5
    head_thickness = 2.0
    overlap = 0.05

    for axis_x, axis_y, feature_name in pin_axes:
        candidates = []
        for solid_index, solid in enumerate(solids):
            if solid_index in used_indices:
                continue
            bb = solid.BoundingBox()
            center = bb.center
            xy_error = ((center.x - axis_x) ** 2 + (center.y - axis_y) ** 2) ** 0.5

            # Long pins are the only narrow solids spanning approximately 54 mm in Z.
            if bb.zlen > 50.0 and bb.xlen < 8.0 and bb.ylen < 8.0:
                candidates.append((xy_error, solid_index, solid, bb))

        if not candidates:
            raise ValueError(f"Could not localize long pin {feature_name}")

        candidates.sort(key=lambda item: item[0])
        xy_error, solid_index, pin_solid, pin_bb = candidates[0]
        if xy_error > 1.0:
            raise ValueError(
                f"Localized solid for {feature_name} is not coaxial; XY error={xy_error:.4f} mm"
            )

        used_indices.add(solid_index)
        print(
            f"Localized {feature_name} as SOLID {solid_index}: "
            f"axis=({axis_x:.6f},{axis_y:.6f}), "
            f"Z ends=({pin_bb.zmin:.6f},{pin_bb.zmax:.6f}), "
            f"size=({pin_bb.xlen:.4f},{pin_bb.ylen:.4f},{pin_bb.zlen:.4f})"
        )

        # Each cylinder overlaps its associated pin by only 0.05 mm for a robust
        # fuse. Its retaining shoulder remains at essentially the original pin end,
        # which already has about 0.5 mm clearance from the adjacent outer link face.
        negative_head = cq.Solid.makeCylinder(
            head_radius,
            head_thickness + overlap,
            cq.Vector(axis_x, axis_y, pin_bb.zmin + overlap),
            cq.Vector(0, 0, -1),
        )
        positive_head = cq.Solid.makeCylinder(
            head_radius,
            head_thickness + overlap,
            cq.Vector(axis_x, axis_y, pin_bb.zmax - overlap),
            cq.Vector(0, 0, 1),
        )

        retained_pin = pin_solid.fuse(negative_head, positive_head)
        if not retained_pin.isValid():
            raise ValueError(f"Head fusion produced an invalid solid for {feature_name}")

        replacements[solid_index] = retained_pin

    # Rebuild the assembly compound while keeping rails, links, and all other pins
    # as distinct solids. Only each long pin is fused to its own two heads.
    output_solids = []
    for index, solid in enumerate(solids):
        output_solids.append(replacements.get(index, solid))

    result = cq.Compound.makeCompound(output_solids)
    print(
        f"Added eight cylindrical retaining heads: diameter={2 * head_radius:.2f} mm, "
        f"thickness={head_thickness:.2f} mm."
    )
    print(f"Output valid: {result.isValid()}, output solids: {len(result.Solids())}")
    return result