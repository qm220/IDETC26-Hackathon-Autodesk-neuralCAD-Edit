def my_cad_function(args):
    import os
    import math
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    solid = model.val()

    print(f"Loaded STEP: {input_file}")
    print(f"Valid before edit: {solid.isValid()}")
    print(f"Solid count before edit: {len(solid.Solids())}")
    print(f"Face count before edit: {len(solid.Faces())}")

    if not solid.isValid() or len(solid.Solids()) != 1:
        raise ValueError("Input STEP must contain one valid solid")

    faces = solid.Faces()

    # Bind the planned FACE 44 and FACE 46 references using their actual STEP
    # geometry. CadQuery Face.radius() is not available for these imported
    # cylindrical faces, so use surface type, bounding dimensions, and axis
    # station instead.
    def is_target_bore_face(face):
        try:
            if face.geomType() != "CYLINDER":
                return False
            bb = face.BoundingBox()
            c = face.Center()
            return (
                abs(bb.xlen - 0.600000) < 2.0e-3
                and abs(bb.ylen - 1.500000) < 2.0e-3
                and abs(bb.zlen - 1.500000) < 2.0e-3
                and abs(c.y - 3.510000) < 2.0e-3
                and abs(c.z - 2.943179) < 2.0e-3
                and (
                    abs(c.x - 4.997640) < 2.0e-3
                    or abs(c.x - 7.247639) < 2.0e-3
                )
            )
        except Exception:
            return False

    bore_faces = []
    for planned_index in (44, 46):
        if planned_index < len(faces) and is_target_bore_face(faces[planned_index]):
            bore_faces.append(faces[planned_index])
            print(f"Bound planned FACE {planned_index} to clevis bore geometry")

    if len(bore_faces) != 2:
        bore_faces = [f for f in faces if is_target_bore_face(f)]
        print(f"Geometric fallback found {len(bore_faces)} target bore faces")

    if len(bore_faces) != 2:
        raise ValueError(
            f"Expected exactly two X-directed clevis bore walls, found {len(bore_faces)}"
        )

    bore_faces.sort(key=lambda f: f.Center().x)

    # The four permitted entrance planes are the original clevis side faces:
    # FACE 78, FACE 90, FACE 89, and FACE 79.
    expected_entrance_x = (4.697641, 5.297640, 6.947640, 7.547638)
    target_edges = []

    for bore_index, bore_face in enumerate(bore_faces, start=1):
        fbb = bore_face.BoundingBox()
        fc = bore_face.Center()
        print(
            f"Clevis bore {bore_index}: center=({fc.x:.6f},{fc.y:.6f},{fc.z:.6f}), "
            f"x-range=({fbb.xmin:.6f},{fbb.xmax:.6f})"
        )

        entrance_edges = []
        for edge in bore_face.Edges():
            try:
                edge_type = edge.geomType()
            except Exception:
                edge_type = "UNKNOWN"

            ebb = edge.BoundingBox()
            ec = edge.Center()
            length = edge.Length()
            print(
                f"  boundary: type={edge_type}, center=({ec.x:.6f},{ec.y:.6f},{ec.z:.6f}), "
                f"size=({ebb.xlen:.6f},{ebb.ylen:.6f},{ebb.zlen:.6f}), "
                f"length={length:.6f}"
            )

            # Radius 0.75 is verified without Edge.radius(): a complete circle
            # has Y/Z extents of 1.5 and circumference 2*pi*0.75. It must lie
            # in a constant-X ear side plane at an axial end of the bore wall.
            if edge_type != "CIRCLE":
                continue
            if ebb.xlen > 1.0e-4:
                continue
            if abs(ebb.ylen - 1.500000) > 2.0e-3:
                continue
            if abs(ebb.zlen - 1.500000) > 2.0e-3:
                continue
            if abs(length - 2.0 * math.pi * 0.750000) > 2.0e-3:
                continue
            if abs(ec.y - 3.510000) > 2.0e-3 or abs(ec.z - 2.943179) > 2.0e-3:
                continue
            if min(abs(ec.x - fbb.xmin), abs(ec.x - fbb.xmax)) > 1.0e-3:
                continue
            if min(abs(ec.x - x) for x in expected_entrance_x) > 1.0e-3:
                continue

            entrance_edges.append(edge)

        if len(entrance_edges) != 2:
            raise ValueError(
                f"Clevis bore {bore_index} should provide two circular entrance edges; "
                f"found {len(entrance_edges)}"
            )
        target_edges.extend(entrance_edges)

    # De-duplicate defensively by the constant-X location and geometric center.
    unique_edges = {}
    for edge in target_edges:
        c = edge.Center()
        key = (round(c.x, 5), round(c.y, 5), round(c.z, 5))
        unique_edges[key] = edge
    target_edges = list(unique_edges.values())
    target_edges.sort(key=lambda e: e.Center().x)

    if len(target_edges) != 4:
        raise ValueError(
            f"Expected exactly four clevis bore entrance edges; found {len(target_edges)}"
        )

    selected_x = [edge.Center().x for edge in target_edges]
    for expected_x in expected_entrance_x:
        if min(abs(x - expected_x) for x in selected_x) > 1.0e-3:
            raise ValueError(f"Missing entrance edge at clevis side plane x={expected_x}")

    print("Selected only the four clevis pin-bore entrance edges:")
    for i, edge in enumerate(target_edges, start=1):
        c = edge.Center()
        print(
            f"  target {i}: x={c.x:.6f}, y={c.y:.6f}, z={c.z:.6f}, "
            f"length={edge.Length():.6f}"
        )

    # Apply the requested symmetric 0.2 mm edge-distance chamfer to all four
    # entrances. No CAD-Y mounting-hole edge is included in target_edges.
    result = cq.Workplane(obj=solid).newObject(target_edges).chamfer(0.2)
    edited = result.val()

    print("Applied 0.200 mm chamfer to four clevis bore entrance edges")
    print(f"Valid after edit: {edited.isValid()}")
    print(f"Solid count after edit: {len(edited.Solids())}")
    print(f"Face count after edit: {len(edited.Faces())}")

    if not edited.isValid():
        raise ValueError("Chamfer operation produced an invalid result")
    if len(edited.Solids()) != 1:
        raise ValueError("Chamfer operation did not preserve a single solid")

    return result
