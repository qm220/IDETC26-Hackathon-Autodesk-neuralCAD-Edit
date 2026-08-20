def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    tol = 1.0e-4
    top_z = shape.BoundingBox().zmax

    # The enlarged end occupies X <= 100. Its lower perimeter already has
    # edge radii: R30 around the front/left region and R5 around the rear
    # region. Add the corresponding radii to its sharp upper perimeter.
    r30_edges = []
    for edge in shape.Edges():
        eb = edge.BoundingBox()
        c = edge.Center()
        on_top = abs(eb.zmin - top_z) < tol and abs(eb.zmax - top_z) < tol
        in_large_end = eb.xmax <= 100.0 + tol
        if on_top and in_large_end and c.y < 294.0:
            r30_edges.append(edge)

    print("R30 target edges:", len(r30_edges))
    for edge in r30_edges:
        c = edge.Center()
        print("  ", edge.geomType(), (c.x, c.y, c.z), edge.Length())

    if not r30_edges:
        raise RuntimeError("Could not identify the sharp upper front/left perimeter of the enlarged end")

    edited = shape.makeFillet(30.0, r30_edges)

    # Re-identify the still-sharp rear upper perimeter after the first fillet.
    r5_edges = []
    for edge in edited.Edges():
        eb = edge.BoundingBox()
        c = edge.Center()
        on_top = abs(eb.zmin - top_z) < tol and abs(eb.zmax - top_z) < tol
        in_large_end = eb.xmax <= 100.0 + tol
        if on_top and in_large_end and c.y >= 294.0 - tol:
            r5_edges.append(edge)

    print("R5 target edges:", len(r5_edges))
    for edge in r5_edges:
        c = edge.Center()
        print("  ", edge.geomType(), (c.x, c.y, c.z), edge.Length())

    if r5_edges:
        edited = edited.makeFillet(5.0, r5_edges)

    print("RESULT VALID:", edited.isValid())
    print("ORIGINAL VOLUME:", shape.Volume())
    print("RESULT VOLUME:", edited.Volume())
    print("ORIGINAL/RESULT FACES:", len(shape.Faces()), len(edited.Faces()))

    return cq.Workplane("XY").newObject([edited])