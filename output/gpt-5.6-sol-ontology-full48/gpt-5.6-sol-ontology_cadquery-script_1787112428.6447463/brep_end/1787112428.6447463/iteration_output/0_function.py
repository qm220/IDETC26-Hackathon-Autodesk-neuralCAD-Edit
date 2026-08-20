def my_cad_function(args):
    import os
    import math

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    solid = imported.val() if hasattr(imported, "val") else imported

    print(f"Loaded STEP: {input_file}")
    print(f"Valid before edit: {solid.isValid()}")
    print(f"Solid count: {len(solid.Solids())}")
    print(f"Face count: {len(solid.Faces())}")

    faces = solid.Faces()
    for i, face in enumerate(faces):
        bb = face.BoundingBox()
        c = face.Center()
        try:
            gt = face.geomType()
        except Exception:
            gt = "UNKNOWN"
        extra = ""
        if gt in ("CYLINDER", "CIRCLE"):
            try:
                extra = f" radius={face.radius():.6f}"
            except Exception:
                pass
        print(
            f"FACE {i}: type={gt} center=({c.x:.6f},{c.y:.6f},{c.z:.6f}) "
            f"bbox=({bb.xmin:.6f},{bb.xmax:.6f}; "
            f"{bb.ymin:.6f},{bb.ymax:.6f}; "
            f"{bb.zmin:.6f},{bb.zmax:.6f}){extra}"
        )

    # Bind the planned FACE 44 and FACE 46 references to the imported geometry.
    # If STEP face ordering differs, fall back to geometric identification of the
    # two radius-0.75, X-directed clevis bore walls.
    expected_indices = (44, 46)
    bore_faces = []

    def is_clevis_bore_face(face):
        try:
            if face.geomType() != "CYLINDER":
                return False
            if abs(face.radius() - 0.75) > 1.0e-4:
                return False
            bb = face.BoundingBox()
            # Each bore occupies a 0.600 mm ear thickness along CAD X and has
            # a 1.500 mm diameter in both CAD Y and CAD Z.
            if abs(bb.xlen - 0.6) > 2.0e-3:
                return False
            if abs(bb.ylen - 1.5) > 2.0e-3 or abs(bb.zlen - 1.5) > 2.0e-3:
                return False
            cy = 0.5 * (bb.ymin + bb.ymax)
            cz = 0.5 * (bb.zmin + bb.zmax)
            return abs(cy - 3.510000) < 2.0e-3 and abs(cz - 2.943179) < 2.0e-3
        except Exception:
            return False

    for idx in expected_indices:
        if idx < len(faces) and is_clevis_bore_face(faces[idx]):
            bore_faces.append(faces[idx])
            print(f"Bound planned FACE {idx} to a verified clevis bore wall")
        else:
            print(f"Planned FACE {idx} did not pass geometric verification")

    if len(bore_faces) != 2:
        bore_faces = [face for face in faces if is_clevis_bore_face(face)]
        print(f"Geometric fallback found {len(bore_faces)} clevis bore faces")

    if len(bore_faces) != 2:
        raise ValueError(
            f"Expected exactly two radius-0.75 X-directed clevis bore faces; found {len(bore_faces)}"
        )

    # Sort along X so diagnostics consistently identify F012 before F013.
    bore_faces.sort(key=lambda f: f.BoundingBox().xmin)

    target_edges = []
    for bore_number, face in enumerate(bore_faces, start=1):
        bb = face.BoundingBox()
        print(
            f"Clevis bore {bore_number}: radius={face.radius():.6f}, "
            f"x limits=({bb.xmin:.6f},{bb.xmax:.6f}), "
            f"axis station y={0.5*(bb.ymin+bb.ymax):.6f}, "
            f"z={0.5*(bb.zmin+bb.zmax):.6f}"
        )

        circular_boundaries = []
        for edge in face.Edges():
            try:
                gt = edge.geomType()
            except Exception:
                gt = "UNKNOWN"
            ebb = edge.BoundingBox()
            ec = edge.Center()
            radius = None
            try:
                radius = edge.radius()
            except Exception:
                pass
            print(
                f"  boundary edge type={gt} radius={radius} "
                f"center=({ec.x:.6f},{ec.y:.6f},{ec.z:.6f}) "
                f"bbox=({ebb.xmin:.6f},{ebb.xmax:.6f};"
                f"{ebb.ymin:.6f},{ebb.ymax:.6f};"
                f"{ebb.zmin:.6f},{ebb.zmax:.6f})"
            )

            if gt != "CIRCLE" or radius is None or abs(radius - 0.75) > 1.0e-4:
                continue
            # A bore entrance is a complete circular edge in a constant-X ear
            # side plane at one of the cylindrical face's axial limits.
            if ebb.xlen > 1.0e-4:
                continue
            x = 0.5 * (ebb.xmin + ebb.xmax)
            if min(abs(x - bb.xmin), abs(x - bb.xmax)) > 1.0e-3:
                continue
            if abs(edge.Length() - 2.0 * math.pi * 0.75) > 2.0e-3:
                continue
            circular_boundaries.append(edge)

        if len(circular_boundaries) != 2:
            raise ValueError(
                f"Clevis bore {bore_number} should have two circular entrance edges; "
                f"found {len(circular_boundaries)}"
            )
        target_edges.extend(circular_boundaries)

    if len(target_edges) != 4:
        raise ValueError(f"Expected four clevis pin-bore rim edges; found {len(target_edges)}")

    print("Selected four clevis pin-bore entrance edges for a 0.200 mm chamfer:")
    for i, edge in enumerate(sorted(target_edges, key=lambda e: e.BoundingBox().xmin), start=1):
        ebb = edge.BoundingBox()
        print(
            f"  target {i}: x={0.5*(ebb.xmin+ebb.xmax):.6f}, "
            f"radius={edge.radius():.6f}, length={edge.Length():.6f}"
        )

    base = cq.Workplane(obj=solid)
    result = base.newObject(target_edges).chamfer(0.2)
    edited = result.val()

    print(f"Applied uniform 0.200 mm chamfer to {len(target_edges)} edges")
    print(f"Valid after edit: {edited.isValid()}")
    print(f"Solid count after edit: {len(edited.Solids())}")
    print(f"Face count after edit: {len(edited.Faces())}")

    if not edited.isValid() or len(edited.Solids()) != 1:
        raise ValueError("Chamfer did not produce one valid solid")

    return result