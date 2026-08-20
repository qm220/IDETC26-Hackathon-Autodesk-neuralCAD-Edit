def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    root = model.val()
    solids = list(root.Solids())

    if len(solids) != 9:
        raise ValueError(f"Expected 9 solids in the assembly, found {len(solids)}")

    # Solid 3 is the separate cylindrical heat-break component centered at
    # approximately (0, -40). Its largest smooth OD is R3.45 and extends from
    # z=7.5 to z=20.8. The existing upper external chamfer is 0.2 x 0.2, so add
    # the matching chamfer to the lower outside circular edge at z=7.5.
    heatbreak = solids[3]
    candidates = []

    for edge in heatbreak.Edges():
        try:
            if edge.geomType() != "CIRCLE":
                continue
            radius = edge.radius()
            center = edge.Center()
            bb = edge.BoundingBox()

            # Circular edges normal to Z have negligible Z extent. Restrict the
            # search to the lower rim of the R3.45 main cylindrical section.
            if (
                abs(radius - 3.45) < 0.05
                and abs(center.x) < 0.05
                and abs(center.y + 40.0) < 0.05
                and abs(center.z - 7.5) < 0.10
                and bb.zlen < 0.01
            ):
                score = abs(radius - 3.45) + abs(center.z - 7.5)
                candidates.append((score, edge, radius, center))
        except Exception:
            pass

    if not candidates:
        raise ValueError("Could not locate the lower outer edge of the heat-break main cylinder")

    candidates.sort(key=lambda item: item[0])
    target_edge = candidates[0][1]
    target_radius = candidates[0][2]
    target_center = candidates[0][3]

    print(
        "Heat-break lower rim selected: "
        f"radius={target_radius:.4f}, "
        f"center=({target_center.x:.4f},{target_center.y:.4f},{target_center.z:.4f})"
    )

    heatbreak_wp = cq.Workplane("XY").newObject([heatbreak])
    edited_wp = heatbreak_wp.newObject([target_edge]).chamfer(0.2)
    edited_heatbreak = edited_wp.val()

    if edited_heatbreak.isNull() or not edited_heatbreak.isValid():
        raise ValueError("The chamfer operation produced an invalid heat-break solid")

    old_volume = heatbreak.Volume()
    new_volume = edited_heatbreak.Volume()
    removed_volume = old_volume - new_volume
    print(
        f"Applied matching 0.2 mm lower external chamfer; "
        f"old volume={old_volume:.6f}, new volume={new_volume:.6f}, "
        f"removed={removed_volume:.6f}"
    )

    if removed_volume <= 0 or removed_volume > 10.0:
        raise ValueError(
            f"Unexpected chamfer volume change ({removed_volume:.6f}); refusing to return the edit"
        )

    # Rebuild the assembly with only the heat-break solid replaced. Every other
    # component remains exactly as imported from the source STEP model.
    solids[3] = edited_heatbreak
    result = cq.Compound.makeCompound(solids)
    return cq.Workplane("XY").newObject([result])