def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    model = imported.val() if hasattr(imported, "val") else imported

    solids = list(model.Solids())
    print(f"Loaded STEP: {input_file}")
    print(f"Model valid before edit: {model.isValid()}")
    print(f"Disconnected solids found: {len(solids)}")

    # Inspect the actual imported geometry before editing. Select R09 by its
    # grounded exploded-layout position rather than relying solely on SOLID 8's
    # ordinal position.
    target_index = None
    best_score = None
    for i, solid in enumerate(solids):
        bb = solid.BoundingBox()
        c = bb.center
        print(
            f"SOLID {i}: center=({c.x:.6f}, {c.y:.6f}, {c.z:.6f}), "
            f"bbox=({bb.xmin:.6f}, {bb.ymin:.6f}, {bb.zmin:.6f}) to "
            f"({bb.xmax:.6f}, {bb.ymax:.6f}, {bb.zmax:.6f}), "
            f"size=({bb.xlen:.6f}, {bb.ylen:.6f}, {bb.zlen:.6f}), "
            f"faces={len(solid.Faces())}"
        )
        # R09 is the long nozzle centered near x=40, y=-60, with its axis on Z.
        score = abs(c.x - 40.0) + abs(c.y + 60.0) + 0.1 * abs(bb.zlen - 21.0)
        if best_score is None or score < best_score:
            best_score = score
            target_index = i

    if target_index is None:
        raise ValueError("Could not locate the R09 Nozzle Volcano solid")

    target = solids[target_index]
    old_bb = target.BoundingBox()
    old_height = old_bb.zlen
    print(f"Selected R09 as imported SOLID {target_index}")
    print(f"R09 original Z extent: {old_bb.zmin:.9f} to {old_bb.zmax:.9f}")
    print(f"R09 original overall height: {old_height:.9f} mm")

    # Bind the planned FACE N references to the actual imported B-rep and print
    # their measured geometry. FACE indices are zero-based CadQuery Faces()
    # indices, as specified by the STEP analysis artifacts.
    all_faces = list(model.Faces())
    grounded_face_ids = [1211, 1212, 1226, 1240, 1241, 1242, 1243, 1244, 1245, 1260, 1269, 1271, 1277]
    print(f"Model face count: {len(all_faces)}")
    for face_id in grounded_face_ids:
        if 0 <= face_id < len(all_faces):
            face = all_faces[face_id]
            fbb = face.BoundingBox()
            fc = face.Center()
            try:
                geom_type = face.geomType()
            except Exception:
                geom_type = "UNKNOWN"
            print(
                f"FACE {face_id}: type={geom_type}, "
                f"center=({fc.x:.6f}, {fc.y:.6f}, {fc.z:.6f}), "
                f"bbox=({fbb.xmin:.6f}, {fbb.ymin:.6f}, {fbb.zmin:.6f}) to "
                f"({fbb.xmax:.6f}, {fbb.ymax:.6f}, {fbb.zmax:.6f}), "
                f"area={face.Area():.9f}"
            )
        else:
            print(f"FACE {face_id}: unavailable; imported model has {len(all_faces)} faces")

    # Also inspect every face belonging to the selected R09 solid so the
    # threaded free end is localized from actual coordinates.
    for local_id, face in enumerate(target.Faces()):
        fbb = face.BoundingBox()
        fc = face.Center()
        try:
            geom_type = face.geomType()
        except Exception:
            geom_type = "UNKNOWN"
        print(
            f"R09 local face {local_id}: type={geom_type}, "
            f"center=({fc.x:.6f}, {fc.y:.6f}, {fc.z:.6f}), "
            f"z=({fbb.zmin:.6f}, {fbb.zmax:.6f})"
        )

    # The nozzle axis is parallel to CAD Z. The free threaded end is the current
    # maximum-Z end. Remove exactly 1 mm using an XY-aligned cutting slab. The
    # cutter spans only R09's XY envelope, so no other exploded component is
    # modified.
    reduction = 1.0
    new_end_z = old_bb.zmax - reduction
    margin = 2.0
    cutter = cq.Solid.makeBox(
        old_bb.xlen + 2.0 * margin,
        old_bb.ylen + 2.0 * margin,
        reduction + 2.0 * margin,
        cq.Vector(old_bb.xmin - margin, old_bb.ymin - margin, new_end_z)
    )
    shortened = target.cut(cutter)

    if shortened is None or shortened.isNull():
        raise ValueError("The R09 threaded-end trim produced a null shape")
    if not shortened.isValid():
        raise ValueError("The shortened R09 shape is invalid")

    shortened_solids = list(shortened.Solids())
    if len(shortened_solids) != 1:
        raise ValueError(
            f"Expected shortened R09 to remain one solid, got {len(shortened_solids)}"
        )
    shortened = shortened_solids[0]

    new_bb = shortened.BoundingBox()
    new_height = new_bb.zlen
    actual_reduction = old_height - new_height
    print(f"R09 new Z extent: {new_bb.zmin:.9f} to {new_bb.zmax:.9f}")
    print(f"R09 new overall height: {new_height:.9f} mm")
    print(f"Measured height reduction: {actual_reduction:.9f} mm")
    print(f"R09 valid after edit: {shortened.isValid()}")
    print(f"R09 resulting solids: {len(shortened.Solids())}")

    if abs(new_bb.zmax - new_end_z) > 1.0e-6:
        raise ValueError(
            f"New threaded end is at z={new_bb.zmax}, expected z={new_end_z}"
        )
    if abs(actual_reduction - reduction) > 1.0e-6:
        raise ValueError(
            f"Height reduction is {actual_reduction} mm rather than 1.000 mm"
        )

    # Reassemble the exploded model without fusing disconnected components.
    # Every non-target solid is reused directly, preserving its geometry and
    # position; only R09 is replaced by the shortened watertight solid.
    output_solids = []
    for i, solid in enumerate(solids):
        output_solids.append(shortened if i == target_index else solid)

    result = cq.Compound.makeCompound(output_solids)
    print(f"Output solid count: {len(result.Solids())}")
    print(f"Output model valid: {result.isValid()}")
    return result