def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val()
    solids = list(root.Solids())

    if len(solids) < 2:
        raise ValueError("Expected separate housing and scroll-wheel solids in the input model")

    # The housing is the dominant solid by volume; all other solids are preserved.
    solids_by_volume = sorted(solids, key=lambda s: s.Volume(), reverse=True)
    housing = solids_by_volume[0]
    preserved_solids = solids_by_volume[1:]

    faces = list(housing.Faces())
    if len(faces) < 7:
        raise ValueError("Housing topology does not contain the expected wheel-well faces")

    # According to the source B-rep topology, faces 0-3 are the four planar
    # wheel-well walls and face 6 is the surrounding ergonomic top deck.
    well_walls = [faces[i] for i in (0, 1, 2, 3)]
    top_deck = faces[6]

    def same_shape(a, b):
        try:
            return a.wrapped.IsSame(b.wrapped)
        except Exception:
            return a.isSame(b)

    # Select only edges shared by the top deck and the four well walls. This
    # excludes the lower wall-to-floor edges and all scroll-wheel edges.
    top_edges = list(top_deck.Edges())
    slot_rim_edges = []
    for wall in well_walls:
        shared = []
        for wall_edge in wall.Edges():
            for deck_edge in top_edges:
                if same_shape(wall_edge, deck_edge):
                    shared.append(wall_edge)
                    break
        for edge in shared:
            if not any(same_shape(edge, existing) for existing in slot_rim_edges):
                slot_rim_edges.append(edge)

    print("Input solids:", len(solids))
    print("Housing faces:", len(faces))
    print("Selected upper wheel-slot rim edges:", len(slot_rim_edges))
    for i, edge in enumerate(slot_rim_edges):
        c = edge.Center()
        print("  edge %d: length=%.6f center=(%.6f, %.6f, %.6f)" %
              (i, edge.Length(), c.x, c.y, c.z))

    if len(slot_rim_edges) != 4:
        raise ValueError(
            "Expected four upper wheel-slot perimeter edges, found %d" %
            len(slot_rim_edges)
        )

    filleted_housing = housing.makeFillet(2.0, slot_rim_edges)
    if not filleted_housing.isValid():
        raise ValueError("The 2 mm wheel-slot fillet produced an invalid housing")

    output_solids = [filleted_housing] + preserved_solids
    result = cq.Compound.makeCompound(output_solids)

    print("Applied a continuous 2.0 mm fillet to the four exposed slot-rim edges")
    print("Result valid:", result.isValid())
    print("Result solids:", len(result.Solids()))
    return result