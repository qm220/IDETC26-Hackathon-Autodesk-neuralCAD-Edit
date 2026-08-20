def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported

    solids = list(root.Solids())
    faces = list(root.Faces())
    if len(solids) < 2 or len(faces) < 15:
        raise ValueError("The imported topology does not match the planned two-solid, fifteen-face model")

    housing = solids[0]
    wheel = solids[1]
    pocket_faces = faces[0:5]
    housing_outer_faces = faces[5:11]

    def edge_occurs_on(edge, face_group):
        return any(
            edge.isSame(face_edge)
            for face in face_group
            for face_edge in face.Edges()
        )

    target_edges = [
        edge for edge in housing.Edges()
        if edge_occurs_on(edge, pocket_faces)
        and edge_occurs_on(edge, housing_outer_faces)
    ]

    if not target_edges:
        raise ValueError("No scrolling-wheel slot opening edges were found")

    filleted_housing = (
        cq.Workplane(obj=housing)
        .newObject(target_edges)
        .fillet(2.0)
        .val()
    )

    if not filleted_housing.isValid():
        raise ValueError("The filleted housing is invalid")

    result = cq.Compound.makeCompound([filleted_housing, wheel])
    return cq.Workplane(obj=result)