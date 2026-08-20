def my_cad_function(args):
    import os
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Defeaturing

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model
    faces = shape.Faces()
    solids = shape.Solids()

    print("Loaded STEP:", input_file)
    print("Input valid:", shape.isValid(), "solids:", len(solids), "faces:", len(faces))

    if len(solids) != 2 or len(faces) <= 580:
        raise ValueError("Expected the analyzed two-solid STEP topology containing FACE 580")

    # Bind the planning-stage identifier to the imported geometry and verify
    # that it is the central annular toroidal blend, rather than another fillet.
    target = faces[580]
    tc = target.Center()
    tb = target.BoundingBox()
    print(
        "Bound FACE 580:", target.geomType(),
        "area=", round(target.Area(), 6),
        "center=", (round(tc.x, 6), round(tc.y, 6), round(tc.z, 6)),
        "bbox=", (round(tb.xmin, 6), round(tb.ymin, 6), round(tb.zmin, 6),
                  round(tb.xmax, 6), round(tb.ymax, 6), round(tb.zmax, 6))
    )
    if target.geomType() != "TORUS" or abs(tc.x) > 0.05 or abs(tc.z) > 0.05:
        raise ValueError("FACE 580 did not bind to the concentric central hub torus")

    owner_index = None
    for si, solid in enumerate(solids):
        if any(f.isSame(target) for f in solid.Faces()):
            owner_index = si
            break
    if owner_index is None:
        raise ValueError("Could not find the solid owning FACE 580")

    carrier = solids[owner_index]
    other_solids = [s for i, s in enumerate(solids) if i != owner_index]
    print("FACE 580 owner solid:", owner_index, "carrier faces:", len(carrier.Faces()))

    # Remove only the grounded toroidal face. OCCT defeaturing extends and
    # intersects its adjacent planar seat and conical hub surface, restoring
    # the sharp, complete annular edge that existed before the fillet.
    defeater = BRepAlgoAPI_Defeaturing()
    defeater.SetShape(carrier.wrapped)
    defeater.AddFace(target.wrapped)
    defeater.Build()
    if not defeater.IsDone():
        raise RuntimeError("OCCT could not remove and heal the central hub fillet")

    healed = cq.Shape.cast(defeater.Shape())
    if not healed.isValid():
        raise RuntimeError("Carrier is invalid after removing FACE 580")
    print("After fillet removal: valid=", healed.isValid(), "faces=", len(healed.Faces()))

    # Locate the restored boundary by geometry, not by the now-obsolete STEP
    # index. It must be a complete concentric circle near y=-4.625 mm shared by
    # the restored planar seat and the extended conical hub transition.
    candidates = []
    healed_faces = healed.Faces()
    for ei, edge in enumerate(healed.Edges()):
        if edge.geomType() != "CIRCLE":
            continue
        ec = edge.Center()
        eb = edge.BoundingBox()
        radius = 0.25 * (eb.xlen + eb.zlen)
        if abs(ec.x) > 0.05 or abs(ec.z) > 0.05:
            continue
        if not (13.0 < radius < 20.0 and -5.2 < ec.y < -4.1):
            continue

        adjacent_types = []
        for face in healed_faces:
            if any(fe.isSame(edge) for fe in face.Edges()):
                adjacent_types.append(face.geomType())

        score = abs(ec.y + 4.62534) + abs(radius - 15.5) * 0.01
        if "PLANE" in adjacent_types and "CONE" in adjacent_types:
            score -= 10.0
        candidates.append((score, ei, edge, radius, adjacent_types))
        print(
            "Restored-edge candidate", ei,
            "center=", (round(ec.x, 6), round(ec.y, 6), round(ec.z, 6)),
            "radius=", round(radius, 6),
            "adjacent=", adjacent_types
        )

    if not candidates:
        raise RuntimeError("No complete restored annular edge was found after defeaturing")

    candidates.sort(key=lambda item: item[0])
    _, edge_index, restored_edge, restored_radius, adjacent_types = candidates[0]
    if "PLANE" not in adjacent_types or "CONE" not in adjacent_types:
        raise RuntimeError("Best restored edge is not the required plane/cone hub boundary")

    print(
        "Selected restored annular edge:", edge_index,
        "radius=", round(restored_radius, 6),
        "adjacent=", adjacent_types
    )

    # Replace the removed fillet with a 1 mm equal-distance chamfer around the
    # entire selected annular edge loop.
    base_wp = cq.Workplane(obj=healed)
    selected_wp = base_wp.newObject([restored_edge])
    chamfered = selected_wp.chamfer(1.0).val()

    if not chamfered.isValid():
        raise RuntimeError("Carrier is invalid after applying the 1 mm chamfer")

    print(
        "Chamfer complete: valid=", chamfered.isValid(),
        "faces=", len(chamfered.Faces()),
        "volume=", round(chamfered.Volume(), 6)
    )

    # Preserve the separate splined insert and return the edited carrier with
    # the original two-component assembly structure.
    result_solids = other_solids + [chamfered]
    result = cq.Compound.makeCompound(result_solids)
    print("Output valid:", result.isValid(), "solids:", len(result.Solids()))
    return cq.Workplane(obj=result)
