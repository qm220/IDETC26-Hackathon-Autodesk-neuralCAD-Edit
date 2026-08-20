def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    tol = 1.0e-4
    top_z = shape.BoundingBox().zmax

    # The visually enlarged end is the region at X <= 100. Its opposite
    # (lower-Z) perimeter already contains matching R30 and R5 fillets.
    # Select the corresponding sharp upper-Z perimeter edges.
    r30_edges = []
    for edge in shape.Edges():
        eb = edge.BoundingBox()
        c = edge.Center()
        on_top = (
            abs(eb.zmin - top_z) < tol
            and abs(eb.zmax - top_z) < tol
        )
        in_large_end = eb.xmax <= 100.0 + tol
        if on_top and in_large_end and c.y < 294.0:
            r30_edges.append(edge)

    print("Top Z:", top_z)
    print("R30 target edges:", len(r30_edges))
    for edge in r30_edges:
        c = edge.Center()
        print("  R30", edge.geomType(), (c.x, c.y, c.z), edge.Length())

    if not r30_edges:
        raise RuntimeError(
            "Could not identify the sharp upper perimeter edges corresponding to the existing R30 fillet"
        )

    # CadQuery Solid exposes fillet(), not makeFillet().
    edited = shape.fillet(30.0, r30_edges)

    # Re-identify the remaining sharp upper perimeter on the enlarged end.
    # These edges correspond to the existing smaller R5 opposite-side fillet.
    edited_top_z = edited.BoundingBox().zmax
    r5_edges = []
    for edge in edited.Edges():
        eb = edge.BoundingBox()
        c = edge.Center()
        on_top = (
            abs(eb.zmin - edited_top_z) < tol
            and abs(eb.zmax - edited_top_z) < tol
        )
        in_large_end = eb.xmax <= 100.0 + tol
        if on_top and in_large_end and c.y >= 294.0 - tol:
            r5_edges.append(edge)

    print("R5 target edges:", len(r5_edges))
    for edge in r5_edges:
        c = edge.Center()
        print("  R5", edge.geomType(), (c.x, c.y, c.z), edge.Length())

    if not r5_edges:
        raise RuntimeError(
            "Could not identify the sharp upper perimeter edges corresponding to the existing R5 fillet"
        )

    edited = edited.fillet(5.0, r5_edges)

    print("RESULT VALID:", edited.isValid())
    print("ORIGINAL VOLUME:", shape.Volume())
    print("RESULT VOLUME:", edited.Volume())
    print("ORIGINAL/RESULT FACES:", len(shape.Faces()), len(edited.Faces()))

    if not edited.isValid():
        raise RuntimeError("The filleted result is not a valid solid")

    return cq.Workplane("XY").newObject([edited])