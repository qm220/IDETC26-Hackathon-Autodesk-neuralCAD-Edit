def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val()

    solids = root.Solids()
    if len(solids) != 1:
        raise ValueError(f"Expected one solid in the input model, found {len(solids)}")
    solid = solids[0]

    faces = solid.Faces()
    target_face_ids = [44, 46, 49, 50, 51, 52]
    target_edges = []

    def add_unique_edge(edge):
        for existing in target_edges:
            if edge.isSame(existing):
                return
        target_edges.append(edge)

    for face_id in target_face_ids:
        face = faces[face_id]
        if face.geomType() != "CYLINDER":
            raise ValueError(f"Target face {face_id} is not cylindrical")
        circular_edges = [edge for edge in face.Edges() if edge.geomType() == "CIRCLE"]
        if len(circular_edges) != 2:
            raise ValueError(f"Target hole face {face_id} does not have two circular rims")
        for edge in circular_edges:
            add_unique_edge(edge)

    if len(target_edges) != 12:
        raise ValueError(f"Expected 12 hole-rim edges, found {len(target_edges)}")

    result = cq.Workplane(obj=solid).newObject(target_edges).chamfer(0.2)
    result_solid = result.val()
    if not result_solid.isValid() or len(result_solid.Solids()) != 1:
        raise ValueError("The chamfer operation did not produce one valid solid")

    print(f"Applied 0.2 mm equal-distance chamfers to {len(target_edges)} hole-rim edges")
    return result