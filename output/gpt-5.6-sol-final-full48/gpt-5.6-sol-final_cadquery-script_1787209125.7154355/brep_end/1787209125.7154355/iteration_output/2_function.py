def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    root = model.val()
    solids = list(root.Solids())

    if len(solids) != 9:
        raise ValueError(f"Expected 9 solids in the assembly, found {len(solids)}")

    heatbreak = solids[3]
    candidates = []

    for edge in heatbreak.Edges():
        try:
            if edge.geomType() != "CIRCLE":
                continue
            radius = edge.radius()
            center = edge.Center()
            bb = edge.BoundingBox()
            if (
                abs(radius - 3.45) < 0.05
                and abs(center.x) < 0.05
                and abs(center.y + 40.0) < 0.05
                and abs(center.z - 7.5) < 0.10
                and bb.zlen < 0.01
            ):
                score = abs(radius - 3.45) + abs(center.z - 7.5)
                candidates.append((score, edge))
        except Exception:
            pass

    if not candidates:
        raise ValueError("Could not locate the lower outer edge of the heat-break main cylinder")

    candidates.sort(key=lambda item: item[0])
    target_edge = candidates[0][1]
    edited_heatbreak = (
        cq.Workplane("XY")
        .newObject([heatbreak])
        .newObject([target_edge])
        .chamfer(0.2)
        .val()
    )

    if edited_heatbreak.isNull() or not edited_heatbreak.isValid():
        raise ValueError("The chamfer operation produced an invalid heat-break solid")

    removed_volume = heatbreak.Volume() - edited_heatbreak.Volume()
    if removed_volume <= 0 or removed_volume > 10.0:
        raise ValueError(f"Unexpected chamfer volume change: {removed_volume:.6f}")

    solids[3] = edited_heatbreak
    result = cq.Compound.makeCompound(solids)
    return cq.Workplane("XY").newObject([result])