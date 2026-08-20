def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported

    solids = list(root.Solids())
    if len(solids) != 2:
        raise ValueError(f"Expected housing and wheel solids, found {len(solids)}")

    # Bind the two components by geometry, independent of STEP ordering.
    housing = max(solids, key=lambda s: s.Volume())
    wheel = min(solids, key=lambda s: s.Volume())
    wheel_volume_before = wheel.Volume()

    housing_faces = list(housing.Faces())
    housing_edges = list(housing.Edges())

    print("SOURCE TOPOLOGY INSPECTION")
    print(
        f"solids={len(solids)} housing_volume={housing.Volume():.6f} "
        f"wheel_volume={wheel_volume_before:.6f}"
    )

    for i, face in enumerate(housing_faces):
        c = face.Center()
        bb = face.BoundingBox()
        try:
            geom_type = face.geomType()
        except Exception:
            geom_type = "UNKNOWN"
        print(
            f"HOUSING FACE {i}: type={geom_type} area={face.Area():.6f} "
            f"center=({c.x:.6f},{c.y:.6f},{c.z:.6f}) "
            f"wires={len(face.Wires())} "
            f"bbox=({bb.xmin:.6f},{bb.ymin:.6f},{bb.zmin:.6f})-"
            f"({bb.xmax:.6f},{bb.ymax:.6f},{bb.zmax:.6f})"
        )

    # Ground FACE 6 as the unique B-spline housing face containing two wires.
    upper_candidates = []
    for face in housing_faces:
        try:
            if face.geomType() == "BSPLINE" and len(face.Wires()) == 2:
                upper_candidates.append(face)
        except Exception:
            pass

    if len(upper_candidates) != 1:
        raise ValueError(
            "Could not uniquely bind the upper ergonomic housing face (FACE 6); "
            f"found {len(upper_candidates)} candidates"
        )

    upper_face = upper_candidates[0]

    # The smaller secondary wire is the complete wheel-slot opening perimeter.
    slot_wire = min(list(upper_face.Wires()), key=lambda wire: wire.Length())
    target_edges = list(slot_wire.Edges())
    if len(target_edges) != 4:
        raise ValueError(
            f"Expected four edges around the wheel-slot opening, found {len(target_edges)}"
        )

    # Verify that the selected rim consists precisely of boundaries between
    # FACE 6 and the four grounded planar pedestal faces FACE 0 through FACE 3.
    adjacent_planar_indices = set()
    print(
        f"BOUND SLOT WIRE: length={slot_wire.Length():.6f} "
        f"edges={len(target_edges)}"
    )

    for edge_i, edge in enumerate(target_edges):
        global_ids = [
            i for i, candidate in enumerate(housing_edges)
            if edge.isSame(candidate)
        ]
        adjacent_indices = []
        for face_i, face in enumerate(housing_faces):
            if any(edge.isSame(face_edge) for face_edge in face.Edges()):
                adjacent_indices.append(face_i)
                try:
                    if face.geomType() == "PLANE":
                        adjacent_planar_indices.add(face_i)
                except Exception:
                    pass

        center = edge.Center()
        print(
            f"TARGET EDGE {edge_i}: global={global_ids} "
            f"length={edge.Length():.6f} "
            f"center=({center.x:.6f},{center.y:.6f},{center.z:.6f}) "
            f"adjacent_faces={adjacent_indices}"
        )

    if adjacent_planar_indices != {0, 1, 2, 3}:
        raise ValueError(
            "The selected secondary wire does not bound all four grounded slot "
            f"faces FACE 0-3; found planar face indices "
            f"{sorted(adjacent_planar_indices)}"
        )

    # Apply a single 2 mm constant-radius fillet operation to only these four
    # housing edges. Workplane.fillet is used because Solid.makeFillet is not a
    # CadQuery API method. The wheel is excluded from the operation.
    housing_wp = cq.Workplane(obj=housing)
    fillet_wp = housing_wp.newObject(target_edges).fillet(2.0)
    filleted_housing = fillet_wp.val()

    if filleted_housing is None:
        raise ValueError("The slot-rim fillet returned no housing shape")
    if not filleted_housing.isValid():
        raise ValueError("The 2 mm slot-rim fillet produced an invalid housing")

    result = cq.Compound.makeCompound([filleted_housing, wheel])
    if not result.isValid():
        raise ValueError("The final housing-and-wheel compound is invalid")

    result_solids = list(result.Solids())
    if len(result_solids) != 2:
        raise ValueError(
            f"Filleting changed the expected two-solid structure; "
            f"found {len(result_solids)} solids"
        )

    resulting_wheel = min(result_solids, key=lambda solid: solid.Volume())
    wheel_volume_after = resulting_wheel.Volume()
    if abs(wheel_volume_after - wheel_volume_before) > 1.0e-6:
        raise ValueError(
            "The separate scroll wheel changed unexpectedly: "
            f"volume {wheel_volume_before:.9f} -> {wheel_volume_after:.9f}"
        )

    print("FILLET COMPLETE")
    print("radius=2.000000 mm")
    print(f"target_slot_edges={len(target_edges)}")
    print(
        f"housing_faces_before={len(housing.Faces())} "
        f"housing_faces_after={len(filleted_housing.Faces())}"
    )
    print(
        f"housing_volume_before={housing.Volume():.6f} "
        f"housing_volume_after={filleted_housing.Volume():.6f}"
    )
    print(f"wheel_volume_preserved={wheel_volume_after:.6f}")
    print(f"result_valid={result.isValid()} result_solids={len(result_solids)}")

    return cq.Workplane(obj=result)