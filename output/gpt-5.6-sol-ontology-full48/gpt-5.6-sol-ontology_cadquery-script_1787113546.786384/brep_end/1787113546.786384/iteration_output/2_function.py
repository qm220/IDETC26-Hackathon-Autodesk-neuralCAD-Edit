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

    # Bind the planning-stage face index to the actual imported geometry.
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
        raise ValueError("FACE 580 did not bind to the concentric central hub toroidal fillet")

    owner_index = None
    for si, solid in enumerate(solids):
        if any(f.isSame(target) for f in solid.Faces()):
            owner_index = si
            break
    if owner_index is None:
        raise ValueError("Could not identify the carrier solid owning FACE 580")

    carrier = solids[owner_index]
    other_solids = [s for i, s in enumerate(solids) if i != owner_index]
    print("FACE 580 owner solid:", owner_index, "carrier faces:", len(carrier.Faces()))

    # Remove only the grounded central toroidal fillet. The correct OCCT API
    # method is AddFaceToRemove; defeaturing then extends and intersects the
    # neighboring support faces to recover the pre-fillet annular edge.
    defeater = BRepAlgoAPI_Defeaturing()
    defeater.SetShape(carrier.wrapped)
    defeater.AddFaceToRemove(target.wrapped)
    defeater.Build()
    if not defeater.IsDone():
        raise RuntimeError("OCCT could not remove and heal the central hub fillet")

    healed = cq.Shape.cast(defeater.Shape())
    if not healed.isValid():
        raise RuntimeError("Carrier is invalid after removal of FACE 580")
    print("After fillet removal: valid=", healed.isValid(), "faces=", len(healed.Faces()))

    # Derive the restored complete circular boundary from the healed topology.
    # Require concentricity, the grounded axial region, and adjacency to the
    # planar/conical support surfaces formerly joined by the torus.
    healed_faces = healed.Faces()
    candidates = []
    for ei, edge in enumerate(healed.Edges()):
        if edge.geomType() != "CIRCLE":
            continue

        ec = edge.Center()
        eb = edge.BoundingBox()
        radius = 0.25 * (eb.xlen + eb.zlen)
        if abs(ec.x) > 0.05 or abs(ec.z) > 0.05:
            continue
        if not (13.0 < radius < 20.0 and -5.2 < ec.y < -4.0):
            continue

        adjacent_types = []
        adjacent_count = 0
        for face in healed_faces:
            if any(fe.isSame(edge) for fe in face.Edges()):
                adjacent_count += 1
                adjacent_types.append(face.geomType())

        score = abs(ec.y + 4.62534) + 0.01 * abs(radius - 15.5)
        if "PLANE" in adjacent_types and "CONE" in adjacent_types:
            score -= 10.0
        if adjacent_count == 2:
            score -= 1.0

        candidates.append((score, ei, edge, radius, adjacent_types, adjacent_count))
        print(
            "Restored-edge candidate", ei,
            "center=", (round(ec.x, 6), round(ec.y, 6), round(ec.z, 6)),
            "radius=", round(radius, 6),
            "adjacent=", adjacent_types,
            "adjacent_count=", adjacent_count
        )

    if not candidates:
        raise RuntimeError("No restored concentric annular edge was found after defeaturing")

    candidates.sort(key=lambda item: item[0])
    _, edge_index, restored_edge, restored_radius, adjacent_types, adjacent_count = candidates[0]
    if "PLANE" not in adjacent_types or "CONE" not in adjacent_types:
        raise RuntimeError("Selected restored edge is not the required plane/cone hub boundary")
    if adjacent_count != 2:
        raise RuntimeError("Selected restored edge is not a normal two-face manifold edge")

    print(
        "Selected restored annular edge:", edge_index,
        "radius=", round(restored_radius, 6),
        "adjacent=", adjacent_types
    )

    # Apply a 1 mm equal-distance chamfer around the complete annular edge.
    selected = cq.Workplane(obj=healed).newObject([restored_edge])
    chamfered = selected.chamfer(1.0).val()
    if not chamfered.isValid():
        raise RuntimeError("Carrier is invalid after applying the 1 mm chamfer")

    # Confirm that a new concentric conical chamfer face exists in the target
    # region, distinct from the original removed toroidal face.
    chamfer_faces = []
    for fi, face in enumerate(chamfered.Faces()):
        fc = face.Center()
        fb = face.BoundingBox()
        if (face.geomType() == "CONE" and abs(fc.x) < 0.1 and abs(fc.z) < 0.1
                and -5.7 < fc.y < -3.8
                and 27.0 < fb.xlen < 40.0 and 27.0 < fb.zlen < 40.0):
            chamfer_faces.append(fi)

    print(
        "Chamfer complete: valid=", chamfered.isValid(),
        "faces=", len(chamfered.Faces()),
        "volume=", round(chamfered.Volume(), 6),
        "central conical candidates=", chamfer_faces
    )
    if not chamfer_faces:
        raise RuntimeError("No central conical face was found to verify the new chamfer")

    # Preserve the separate splined insert and the two-solid assembly structure.
    result = cq.Compound.makeCompound(other_solids + [chamfered])
    print("Output valid:", result.isValid(), "solids:", len(result.Solids()))
    if not result.isValid() or len(result.Solids()) != 2:
        raise RuntimeError("Edited assembly is invalid or no longer contains two solids")

    return cq.Workplane(obj=result)