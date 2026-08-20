def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported

    solids = list(root.Solids())
    print(f"Loaded STEP: {input_file}")
    print(f"Root valid: {root.isValid()}")
    print(f"Detected solids: {len(solids)}")

    for i, solid in enumerate(solids):
        bb = solid.BoundingBox()
        c = solid.Center()
        print(
            f"SOLID {i}: volume={solid.Volume():.6f}, "
            f"center=({c.x:.4f},{c.y:.4f},{c.z:.4f}), "
            f"bbox=({bb.xmin:.4f},{bb.ymin:.4f},{bb.zmin:.4f}) to "
            f"({bb.xmax:.4f},{bb.ymax:.4f},{bb.zmax:.4f}), "
            f"size=({bb.xlen:.4f},{bb.ylen:.4f},{bb.zlen:.4f}), "
            f"faces={len(solid.Faces())}"
        )

    if len(solids) <= 8:
        raise ValueError(f"Expected SOLID 8, but STEP contains only {len(solids)} solids")

    # Ground F009 / SOLID 8 against the actual imported geometry before editing.
    target_index = 8
    target = solids[target_index]
    target_bb = target.BoundingBox()
    original_height = target_bb.zlen
    trim_amount = 1.0
    trim_z = target_bb.zmax - trim_amount

    print("Inspecting faces of grounded target SOLID 8 (F009 long nozzle fitting):")
    for face_index, face in enumerate(target.Faces()):
        fc = face.Center()
        fb = face.BoundingBox()
        try:
            geom_type = face.geomType()
        except Exception:
            geom_type = "UNKNOWN"
        try:
            normal = face.normalAt()
            normal_text = f"({normal.x:.4f},{normal.y:.4f},{normal.z:.4f})"
        except Exception:
            normal_text = "unavailable"
        print(
            f"FACE {face_index}: type={geom_type}, "
            f"center=({fc.x:.4f},{fc.y:.4f},{fc.z:.4f}), normal={normal_text}, "
            f"zrange=({fb.zmin:.4f},{fb.zmax:.4f}), area={face.Area():.6f}"
        )

    print(
        f"Trimming SOLID 8 at Z={trim_z:.6f}; original z-range "
        f"[{target_bb.zmin:.6f}, {target_bb.zmax:.6f}] and height={original_height:.6f}"
    )

    # Remove only the material above the plane one millimetre below the target's
    # top extent. The oversized removal prism avoids dependence on model origin.
    margin = max(target_bb.xlen, target_bb.ylen, target_bb.zlen, 1.0) + 5.0
    removal = cq.Solid.makeBox(
        target_bb.xlen + 2.0 * margin,
        target_bb.ylen + 2.0 * margin,
        trim_amount + margin,
        cq.Vector(target_bb.xmin - margin, target_bb.ymin - margin, trim_z)
    )
    shortened = target.cut(removal)

    if shortened.isNull() or not shortened.isValid():
        raise ValueError("Trim operation produced an invalid SOLID 8")

    shortened_bb = shortened.BoundingBox()
    actual_reduction = original_height - shortened_bb.zlen
    print(
        f"Shortened SOLID 8: z-range=[{shortened_bb.zmin:.6f}, "
        f"{shortened_bb.zmax:.6f}], height={shortened_bb.zlen:.6f}, "
        f"reduction={actual_reduction:.6f} mm, valid={shortened.isValid()}"
    )

    if abs(actual_reduction - trim_amount) > 1.0e-5:
        raise ValueError(
            f"Expected a 1.0 mm height reduction, obtained {actual_reduction:.6f} mm"
        )

    # Preserve every other imported body exactly and replace only SOLID 8.
    result_solids = [shortened if i == target_index else solid for i, solid in enumerate(solids)]
    result = cq.Compound.makeCompound(result_solids)
    print(f"Result contains {len(result.Solids())} solids and isValid={result.isValid()}")
    return result