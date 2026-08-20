def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    root = model.val()
    solids = list(root.Solids())

    if not solids:
        raise ValueError("The imported STEP model contains no solids.")

    # The unrounded blade edge is the unique full-length straight edge on
    # solid 0. Its measured length is 381 mm and it lies on Y = 0. The other
    # blade (solid 1) already has rounded longitudinal sides and consequently
    # has no corresponding full-length straight edge.
    blade = solids[0]
    candidates = []
    for edge in blade.Edges():
        if edge.geomType() != "LINE":
            continue
        bb = edge.BoundingBox()
        center = edge.Center()
        length = edge.Length()
        if length > 300.0 and bb.ylen < 1.0e-5 and abs(center.y) < 1.0e-4:
            candidates.append(edge)

    if len(candidates) != 1:
        details = [
            (e.Length(), e.Center().x, e.Center().y, e.Center().z)
            for e in candidates
        ]
        raise ValueError(
            "Expected one unrounded full-length blade edge, found %d: %s"
            % (len(candidates), details)
        )

    target_edge = candidates[0]
    requested_radius_mm = 6.35

    print(
        "Applying R=6.35 mm fillet to straight blade edge:",
        "length=", round(target_edge.Length(), 6),
        "center=", tuple(round(v, 6) for v in (
            target_edge.Center().x,
            target_edge.Center().y,
            target_edge.Center().z,
        )),
    )

    edited_blade = blade.fillet(requested_radius_mm, [target_edge])

    if edited_blade is None or edited_blade.isNull():
        raise RuntimeError("The 6.35 mm blade-edge fillet produced a null shape.")

    if not edited_blade.isValid():
        raise RuntimeError("The blade is invalid after applying the 6.35 mm fillet.")

    # Preserve every other component exactly as imported.
    output_solids = [edited_blade] + solids[1:]
    result = cq.Compound.makeCompound(output_solids)

    print("Original blade volume:", round(blade.Volume(), 6))
    print("Edited blade volume:", round(edited_blade.Volume(), 6))
    print("Original blade faces/edges:", len(blade.Faces()), len(blade.Edges()))
    print("Edited blade faces/edges:", len(edited_blade.Faces()), len(edited_blade.Edges()))
    print("Preserved additional solids:", len(solids) - 1)

    return cq.Workplane("XY").newObject([result])