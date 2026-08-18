def my_cad_function(args):
    import os
    import math
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    root = model.val() if hasattr(model, "val") else model
    solids = list(root.Solids())

    print(f"Loaded STEP: {input_file}")
    print(f"Input solids: {len(solids)}, valid: {root.isValid()}")
    if len(solids) != 3:
        raise ValueError(f"Expected the three-solid assembly, but found {len(solids)} solids")

    # SEC_01 is the long diagonal crossbar and has the greatest X extent.
    diagonal_index = max(
        range(len(solids)),
        key=lambda i: solids[i].BoundingBox().xlen
    )
    diagonal = solids[diagonal_index]
    source_bb = diagonal.BoundingBox()
    source_volume = diagonal.Volume()

    # Locate the remaining sharp longitudinal edge shared by the broad
    # underside and narrow side. It is the long straight edge on the minimum-Y
    # surface of SEC_01. Selection is geometric rather than STEP-index based.
    candidates = []
    for edge_index, edge in enumerate(diagonal.Edges()):
        try:
            if edge.geomType() != "LINE":
                continue

            length = edge.Length()
            vertices = edge.Vertices()
            if len(vertices) < 2:
                continue

            p0 = vertices[0].Center()
            p1 = vertices[-1].Center()
            dx = p1.x - p0.x
            dy = p1.y - p0.y
            dz = p1.z - p0.z
            magnitude = math.sqrt(dx * dx + dy * dy + dz * dz)
            if magnitude < 1.0e-9:
                continue

            direction = (dx / magnitude, dy / magnitude, dz / magnitude)
            midpoint = edge.Center()
            is_longitudinal = (
                length > 0.90 * max(source_bb.xlen, source_bb.zlen)
                and abs(direction[1]) < 1.0e-6
                and abs(midpoint.y - source_bb.ymin) < 1.0e-5
            )

            if is_longitudinal:
                candidates.append(
                    (length, edge_index, edge, midpoint, direction)
                )
        except Exception as exc:
            print(f"Skipped edge {edge_index}: {exc}")

    if not candidates:
        raise ValueError(
            "Could not locate the sharp underside/side longitudinal edge of SEC_01"
        )

    candidates.sort(key=lambda item: item[0], reverse=True)
    length, edge_index, target_edge, midpoint, direction = candidates[0]
    print(
        f"Selected SEC_01 edge {edge_index}: length={length:.6f} mm, "
        f"mid=({midpoint.x:.6f},{midpoint.y:.6f},{midpoint.z:.6f}), "
        f"dir=({direction[0]:.6f},{direction[1]:.6f},{direction[2]:.6f})"
    )

    if length < 350.0:
        raise ValueError(
            f"Selected edge is unexpectedly short ({length:.6f} mm)"
        )

    # CadQuery Solid exposes fillet(), not makeFillet(). Apply the requested
    # exact constant radius only to the selected longitudinal edge.
    radius = 6.35
    modified_diagonal = diagonal.fillet(radius, [target_edge])

    if modified_diagonal is None:
        raise RuntimeError("The fillet operation returned no solid")
    if not modified_diagonal.isValid():
        raise RuntimeError(
            "The exact 6.35 mm constant-radius fillet produced an invalid SEC_01 solid"
        )

    modified_bb = modified_diagonal.BoundingBox()
    modified_volume = modified_diagonal.Volume()
    print(f"Applied constant-radius fillet R={radius:.6f} mm")
    print(
        f"SEC_01 volume: {source_volume:.6f} -> {modified_volume:.6f} mm^3; "
        f"faces: {len(diagonal.Faces())} -> {len(modified_diagonal.Faces())}"
    )
    print(
        f"SEC_01 bbox after edit: "
        f"({modified_bb.xmin:.3f},{modified_bb.ymin:.3f},{modified_bb.zmin:.3f}) "
        f"to ({modified_bb.xmax:.3f},{modified_bb.ymax:.3f},{modified_bb.zmax:.3f})"
    )

    # Preserve SEC_02 and the combined housing/pivot solid unchanged.
    output_solids = list(solids)
    output_solids[diagonal_index] = modified_diagonal
    result = cq.Compound.makeCompound(output_solids)

    if not result.isValid():
        raise RuntimeError("Reassembled three-solid result is invalid")

    print(f"Output solids: {len(result.Solids())}, valid: {result.isValid()}")
    return cq.Workplane("XY").newObject([result])