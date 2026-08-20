def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    imported = model.val()
    solids = list(imported.Solids())

    if len(solids) != 3:
        raise ValueError("Expected 3 solids, found %d" % len(solids))

    # Ground R01 from its characteristic STEP bounding box.
    target_index = min(
        range(len(solids)),
        key=lambda i: (
            abs(solids[i].BoundingBox().xlen - 331.753222)
            + abs(solids[i].BoundingBox().ylen - 12.700000)
            + abs(solids[i].BoundingBox().zlen - 231.430908)
        )
    )
    target_solid = solids[target_index]
    bb = target_solid.BoundingBox()

    print("=== R01 fillet grounding ===")
    print("Selected solid:", target_index)
    print("R01 bbox: %.6f %.6f %.6f" % (bb.xlen, bb.ylen, bb.zlen))

    # The inspected STEP topology contains one continuous straight 381 mm
    # boundary at y=0 on R01. This is the sharp blade boundary belonging to
    # the long planar side and lying opposite the existing rounded wall.
    # End, bore, transverse-hole, pivot-bore, and transition edges are much
    # shorter or non-linear and are excluded by these geometric constraints.
    candidates = []
    for ei, edge in enumerate(target_solid.Edges()):
        try:
            geom_type = edge.geomType()
        except Exception:
            geom_type = "UNKNOWN"

        length = edge.Length()
        center = edge.Center()
        if geom_type == "LINE" and abs(length - 381.0) < 0.05 and abs(center.y) < 0.01:
            p0 = edge.startPoint()
            p1 = edge.endPoint()
            candidates.append((ei, edge))
            print(
                "Target candidate %d: L=%.6f C=(%.6f,%.6f,%.6f) "
                "P0=(%.6f,%.6f,%.6f) P1=(%.6f,%.6f,%.6f)"
                % (ei, length, center.x, center.y, center.z,
                   p0.x, p0.y, p0.z, p1.x, p1.y, p1.z)
            )

    if len(candidates) != 1:
        raise ValueError(
            "Expected exactly one grounded 381 mm sharp longitudinal edge; found %d"
            % len(candidates)
        )

    selected_index, selected_edge = candidates[0]

    # The nominal requested radius is 6.350 mm. It equals the limiting
    # half-thickness of this imported blade. OCC cannot construct the exact
    # limiting fillet because it collapses the adjacent residual face to zero
    # width (BRep_API NotDone). Use the closest modeling-tolerance equivalent
    # first, only relaxing by additional microns if the STEP tolerances demand
    # it. The resulting radius is nominally R6.35 mm.
    trial_radii = [6.3499, 6.349, 6.345, 6.340]
    edited_solid = None
    used_radius = None

    for radius in trial_radii:
        try:
            print("Trying nominal R6.350 fillet with OCC radius %.4f mm on edge %d"
                  % (radius, selected_index))
            candidate = target_solid.fillet(radius, [selected_edge])
            if candidate.ShapeType() == "Solid" and candidate.isValid():
                edited_solid = candidate
                used_radius = radius
                break
        except Exception as exc:
            print("Fillet attempt %.4f mm failed: %s" % (radius, exc))

    if edited_solid is None:
        raise ValueError("OCC could not create the nominal R6.35 mm target-edge fillet")

    print("Fillet completed on grounded edge %d" % selected_index)
    print("Requested radius: 6.350000 mm")
    print("Kernel radius used: %.6f mm" % used_radius)
    print("Original R01 volume: %.6f" % target_solid.Volume())
    print("Edited R01 volume:   %.6f" % edited_solid.Volume())
    print("Original R01 faces: %d" % len(target_solid.Faces()))
    print("Edited R01 faces:   %d" % len(edited_solid.Faces()))

    # Replace only R01. Preserve the other two solids and assembly placement.
    output_solids = list(solids)
    output_solids[target_index] = edited_solid
    result = cq.Compound.makeCompound(output_solids)

    if len(result.Solids()) != 3:
        raise ValueError("Result no longer contains the original three solids")
    if not result.isValid():
        raise ValueError("Resulting compound is invalid")

    print("Result solids:", len(result.Solids()))
    print("Result valid:", result.isValid())
    return cq.Workplane(obj=result)