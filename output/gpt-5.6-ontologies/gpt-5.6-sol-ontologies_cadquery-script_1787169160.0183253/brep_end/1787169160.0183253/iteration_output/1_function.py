def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    if not shape.isValid():
        raise ValueError("Imported STEP model is invalid")

    # Bore-wall faces identified from the original model:
    # FACE 44 and 46 are the paired clevis pin bores.
    # FACE 49 through 52 are the four mounting holes.
    bore_face_ids = [44, 46, 49, 50, 51, 52]
    faces = shape.Faces()
    target_edges = []

    # Each full cylindrical bore face has two circular boundary edges and one
    # seam edge. Chamfer both accessible ends of every identified hole.
    for face_id in bore_face_ids:
        if face_id >= len(faces):
            raise IndexError(f"Expected bore FACE {face_id}, but model has only {len(faces)} faces")

        face = faces[face_id]
        if face.geomType() != "CYLINDER":
            raise ValueError(f"FACE {face_id} is not cylindrical: {face.geomType()}")

        circular_edges = [edge for edge in face.Edges() if edge.geomType() == "CIRCLE"]
        if len(circular_edges) != 2:
            raise ValueError(
                f"Expected two circular boundary edges on bore FACE {face_id}, "
                f"found {len(circular_edges)}"
            )

        for edge in circular_edges:
            if not any(edge.wrapped.IsSame(existing.wrapped) for existing in target_edges):
                target_edges.append(edge)

    if len(target_edges) != 12:
        raise ValueError(f"Expected 12 unique hole-end edges, found {len(target_edges)}")

    # Apply a symmetric 0.2 mm chamfer to all hole-end edges in one operation.
    edited_shape = shape.chamfer(0.2, None, target_edges)

    if not edited_shape.isValid():
        raise ValueError("Chamfer operation produced an invalid shape")
    if len(edited_shape.Solids()) != 1:
        raise ValueError(
            f"Chamfer operation should preserve one solid, found {len(edited_shape.Solids())}"
        )

    original_bb = shape.BoundingBox()
    edited_bb = edited_shape.BoundingBox()
    print(f"Chamfered hole-end edges: {len(target_edges)}")
    print("Chamfer size: 0.2 mm")
    print(f"Original faces: {len(shape.Faces())}; edited faces: {len(edited_shape.Faces())}")
    print(f"Original volume: {shape.Volume():.9f}; edited volume: {edited_shape.Volume():.9f}")
    print(
        "Original bbox: "
        f"x=({original_bb.xmin:.6f},{original_bb.xmax:.6f}), "
        f"y=({original_bb.ymin:.6f},{original_bb.ymax:.6f}), "
        f"z=({original_bb.zmin:.6f},{original_bb.zmax:.6f})"
    )
    print(
        "Edited bbox: "
        f"x=({edited_bb.xmin:.6f},{edited_bb.xmax:.6f}), "
        f"y=({edited_bb.ymin:.6f},{edited_bb.ymax:.6f}), "
        f"z=({edited_bb.zmin:.6f},{edited_bb.zmax:.6f})"
    )

    return cq.Workplane(obj=edited_shape)