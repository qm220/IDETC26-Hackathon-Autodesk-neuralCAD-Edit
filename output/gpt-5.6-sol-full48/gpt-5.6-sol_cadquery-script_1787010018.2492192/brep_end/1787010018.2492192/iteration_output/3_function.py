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
        raise ValueError(f"Expected 3 assembly solids, found {len(solids)}")

    # SEC_01 is the diagonal member with the greatest global X extent.
    diagonal_index = max(
        range(len(solids)),
        key=lambda i: solids[i].BoundingBox().xlen
    )
    diagonal = solids[diagonal_index]
    bb = diagonal.BoundingBox()
    original_volume = diagonal.Volume()

    # Find the long, straight, diagonal edge lying on the minimum-Y boundary.
    # This is the sharp intersection between the broad underside and narrow
    # longitudinal side, opposite the existing rounded rail.
    candidates = []
    for edge_index, edge in enumerate(diagonal.Edges()):
        try:
            if edge.geomType() != "LINE":
                continue

            vertices = edge.Vertices()
            if len(vertices) < 2:
                continue

            p0 = vertices[0].Center()
            p1 = vertices[-1].Center()
            dx = p1.x - p0.x
            dy = p1.y - p0.y
            dz = p1.z - p0.z
            chord = math.sqrt(dx * dx + dy * dy + dz * dz)
            if chord < 1.0e-9:
                continue

            length = edge.Length()
            midpoint = edge.Center()
            direction = (dx / chord, dy / chord, dz / chord)

            if (
                length > 0.85 * math.hypot(bb.xlen, bb.zlen)
                and abs(direction[1]) < 1.0e-5
                and abs(midpoint.y - bb.ymin) < 1.0e-4
            ):
                candidates.append(
                    (length, edge_index, edge, midpoint, direction)
                )
        except Exception as exc:
            print(f"Skipped edge {edge_index}: {exc}")

    if not candidates:
        raise ValueError(
            "Could not locate the remaining sharp longitudinal edge of SEC_01"
        )

    candidates.sort(key=lambda item: item[0], reverse=True)
    length, edge_index, target_edge, midpoint, direction = candidates[0]
    print(
        f"Target SEC_01 edge {edge_index}: length={length:.6f} mm, "
        f"mid=({midpoint.x:.6f},{midpoint.y:.6f},{midpoint.z:.6f}), "
        f"dir=({direction[0]:.6f},{direction[1]:.6f},{direction[2]:.6f})"
    )

    # The nominal 6.35 mm value is exactly the limiting half-section radius.
    # OCC cannot construct the mathematically degenerate exact-limit edge
    # fillet (the previous BRep_API command-not-done failure). Start only one
    # micron below nominal, which preserves the requested R6.35 dimension at
    # ordinary CAD precision, and retain progressively smaller near-nominal
    # attempts solely for kernel robustness.
    trial_radii = [6.349, 6.345, 6.34, 6.33, 6.30]
    modified_diagonal = None
    applied_radius = None
    failures = []

    for radius in trial_radii:
        try:
            trial = diagonal.fillet(radius, [target_edge])
            if trial is not None and trial.isValid():
                modified_diagonal = trial
                applied_radius = radius
                break
            failures.append(f"R={radius:.3f}: invalid result")
        except Exception as exc:
            failures.append(f"R={radius:.3f}: {type(exc).__name__}: {exc}")

    if modified_diagonal is None:
        raise RuntimeError(
            "Unable to construct the requested near-limit longitudinal fillet; "
            + " | ".join(failures)
        )

    new_volume = modified_diagonal.Volume()
    if new_volume >= original_volume:
        raise RuntimeError(
            "Fillet did not remove material from the selected sharp edge"
        )

    print(
        f"Applied nominal R=6.35 mm longitudinal fillet using kernel-safe "
        f"radius {applied_radius:.3f} mm"
    )
    if failures:
        print("Prior failed attempts: " + " | ".join(failures))
    print(
        f"SEC_01 faces: {len(diagonal.Faces())} -> "
        f"{len(modified_diagonal.Faces())}; volume: "
        f"{original_volume:.6f} -> {new_volume:.6f} mm^3"
    )

    # Replace SEC_01 only. SEC_02 and the housing/pivot solid remain exactly
    # as imported from the original STEP assembly.
    output_solids = list(solids)
    output_solids[diagonal_index] = modified_diagonal
    result = cq.Compound.makeCompound(output_solids)

    if len(result.Solids()) != 3:
        raise RuntimeError(
            f"Expected 3 output solids, found {len(result.Solids())}"
        )
    if not result.isValid():
        raise RuntimeError("Reassembled edited model is invalid")

    print(f"Output solids: {len(result.Solids())}, valid: {result.isValid()}")
    return cq.Workplane("XY").newObject([result])