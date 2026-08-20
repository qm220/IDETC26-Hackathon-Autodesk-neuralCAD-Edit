def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    imported = model.val()
    solids = list(imported.Solids())

    if len(solids) != 3:
        raise ValueError("Expected 3 solids in the imported assembly, found %d" % len(solids))

    # Ground R01 by its characteristic oblique-arm bounding dimensions.
    target_index = min(
        range(len(solids)),
        key=lambda i: (
            abs(solids[i].BoundingBox().xlen - 331.753222)
            + abs(solids[i].BoundingBox().ylen - 12.700000)
            + abs(solids[i].BoundingBox().zlen - 231.430908)
        )
    )
    target_solid = solids[target_index]

    print("=== Fillet target grounding ===")
    print("Selected R01 solid index:", target_index)
    bb = target_solid.BoundingBox()
    print("R01 bbox: (%.6f, %.6f, %.6f)" % (bb.xlen, bb.ylen, bb.zlen))

    # FACE 21 is the long planar wall at transverse coordinate +12.7 mm.
    # Its sharp boundary opposite the existing FACE 20 cylindrical wall is
    # the continuous 381 mm line at y=0. In the inspected STEP this was
    # SOLID 0 edge 52, shared by FACE 21 and the bottom planar shaft face.
    candidates = []
    for ei, edge in enumerate(target_solid.Edges()):
        try:
            edge_type = edge.geomType()
        except Exception:
            edge_type = "UNKNOWN"
        if edge_type != "LINE":
            continue

        length = edge.Length()
        center = edge.Center()
        if abs(length - 381.0) < 0.05 and abs(center.y) < 0.01:
            candidates.append((ei, edge))
            p0 = edge.startPoint()
            p1 = edge.endPoint()
            print(
                "Candidate edge %d: length=%.6f center=(%.6f, %.6f, %.6f) "
                "p0=(%.6f, %.6f, %.6f) p1=(%.6f, %.6f, %.6f)"
                % (ei, length, center.x, center.y, center.z,
                   p0.x, p0.y, p0.z, p1.x, p1.y, p1.z)
            )

    if len(candidates) != 1:
        raise ValueError(
            "Expected exactly one continuous 381 mm sharp longitudinal edge "
            "on R01 at y=0, found %d" % len(candidates)
        )

    selected_index, selected_edge = candidates[0]
    radius = 6.35  # 0.635 cm
    print("Applying R=%.6f mm fillet to R01 edge %d" % (radius, selected_index))

    # Select only the grounded longitudinal edge. End, bore, transverse-hole,
    # pivot-bore, and localized transition edges are deliberately excluded.
    edited_solid = target_solid.makeFillet(radius, [selected_edge])

    if not edited_solid.isValid():
        raise ValueError("The filleted R01 solid is invalid")

    print("Original R01 volume: %.6f" % target_solid.Volume())
    print("Edited R01 volume:   %.6f" % edited_solid.Volume())
    print("Edited R01 faces: %d" % len(edited_solid.Faces()))

    # Preserve the two non-target solids exactly and restore the assembly-like
    # compound without fusing its separate components.
    output_solids = list(solids)
    output_solids[target_index] = edited_solid
    result = cq.Compound.makeCompound(output_solids)

    print("Result solids:", len(result.Solids()))
    print("Result valid:", result.isValid())
    return cq.Workplane(obj=result)