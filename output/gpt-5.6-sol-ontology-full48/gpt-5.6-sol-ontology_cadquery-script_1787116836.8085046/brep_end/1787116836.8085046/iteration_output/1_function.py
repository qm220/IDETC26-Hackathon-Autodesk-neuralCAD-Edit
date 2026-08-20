def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported

    solids = list(root.Solids())
    if len(solids) != 2:
        raise ValueError(f"Expected housing and wheel solids, found {len(solids)} solids")

    # Bind the parts geometrically rather than relying on compound ordering.
    housing = max(solids, key=lambda s: s.Volume())
    wheel = min(solids, key=lambda s: s.Volume())
    wheel_volume_before = wheel.Volume()

    print("SOURCE TOPOLOGY INSPECTION")
    print(f"solids={len(solids)} housing_volume={housing.Volume():.6f} wheel_volume={wheel_volume_before:.6f}")

    housing_faces = list(housing.Faces())
    housing_edges = list(housing.Edges())
    for i, face in enumerate(housing_faces):
        c = face.Center()
        bb = face.BoundingBox()
        try:
            gt = face.geomType()
        except Exception:
            gt = "UNKNOWN"
        print(
            f"HOUSING FACE {i}: type={gt} area={face.Area():.6f} "
            f"center=({c.x:.6f},{c.y:.6f},{c.z:.6f}) wires={len(face.Wires())} "
            f"bbox=({bb.xmin:.6f},{bb.ymin:.6f},{bb.zmin:.6f})-"
            f"({bb.xmax:.6f},{bb.ymax:.6f},{bb.zmax:.6f})"
        )

    # FACE 6 in the STEP analysis is the only large B-spline housing face with
    # two wires. Its shorter secondary wire is the scroll-wheel-slot rim.
    upper_candidates = []
    for face in housing_faces:
        try:
            is_bspline = face.geomType() == "BSPLINE"
        except Exception:
            is_bspline = False
        if is_bspline and len(face.Wires()) == 2:
            upper_candidates.append(face)

    if len(upper_candidates) != 1:
        raise ValueError(
            f"Could not uniquely bind FACE 6 upper housing surface; found {len(upper_candidates)} candidates"
        )

    upper_face = upper_candidates[0]
    wires = list(upper_face.Wires())
    slot_wire = min(wires, key=lambda w: w.Length())
    target_edges = list(slot_wire.Edges())

    if len(target_edges) != 4:
        raise ValueError(f"Expected four continuous slot-rim edges, found {len(target_edges)}")

    # Confirm that each selected edge is shared with one of the four planar
    # pedestal/slot walls corresponding to grounded FACE 0 through FACE 3.
    planar_faces = []
    for face in housing_faces:
        try:
            if face.geomType() == "PLANE":
                planar_faces.append(face)
        except Exception:
            pass

    print(f"BOUND SLOT WIRE: length={slot_wire.Length():.6f} edges={len(target_edges)}")
    adjacent_planar_faces = set()
    for edge_i, edge in enumerate(target_edges):
        ec = edge.Center()
        global_ids = [i for i, candidate in enumerate(housing_edges) if edge.isSame(candidate)]
        adjacent = []
        for face_i, face in enumerate(housing_faces):
            if any(edge.isSame(fe) for fe in face.Edges()):
                adjacent.append(face_i)
                try:
                    if face.geomType() == "PLANE":
                        adjacent_planar_faces.add(face_i)
                except Exception:
                    pass
        print(
            f"TARGET EDGE {edge_i}: global={global_ids} length={edge.Length():.6f} "
            f"center=({ec.x:.6f},{ec.y:.6f},{ec.z:.6f}) adjacent_faces={adjacent}"
        )

    if len(adjacent_planar_faces) != 4:
        raise ValueError(
            "The secondary wire did not bind to all four grounded planar slot faces; "
            f"adjacent planar housing face indices were {sorted(adjacent_planar_faces)}"
        )

    # Apply one constant-radius operation to the complete continuous opening
    # perimeter. Only the housing solid participates; the separate wheel is
    # retained verbatim.
    filleted_housing = housing.makeFillet(2.0, target_edges)
    if not filleted_housing.isValid():
        raise ValueError("The 2 mm slot-rim fillet produced an invalid housing")

    result = cq.Compound.makeCompound([filleted_housing, wheel])
    if not result.isValid():
        raise ValueError("Final housing-and-wheel compound is invalid")

    result_solids = list(result.Solids())
    if len(result_solids) != 2:
        raise ValueError(f"Fillet changed the expected two-solid structure: {len(result_solids)} solids")

    resulting_wheel = min(result_solids, key=lambda s: s.Volume())
    wheel_volume_after = resulting_wheel.Volume()
    if abs(wheel_volume_after - wheel_volume_before) > 1.0e-6:
        raise ValueError(
            f"Wheel geometry changed unexpectedly: {wheel_volume_before} -> {wheel_volume_after}"
        )

    print("FILLET COMPLETE")
    print("radius=2.000000 mm")
    print(f"housing_faces_before={len(housing.Faces())} housing_faces_after={len(filleted_housing.Faces())}")
    print(f"housing_volume_before={housing.Volume():.6f} housing_volume_after={filleted_housing.Volume():.6f}")
    print(f"wheel_volume_preserved={wheel_volume_after:.6f}")
    print(f"result_valid={result.isValid()} result_solids={len(result_solids)}")

    return cq.Workplane(obj=result)
