def my_cad_function(args):
    import os
    import math
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    root = model.val() if hasattr(model, "val") else model
    solids = list(root.Solids())

    if len(solids) != 3:
        raise ValueError(f"Expected 3 assembly solids, found {len(solids)}")

    diagonal_index = max(range(len(solids)), key=lambda i: solids[i].BoundingBox().xlen)
    diagonal = solids[diagonal_index]
    bb = diagonal.BoundingBox()

    candidates = []
    for edge_index, edge in enumerate(diagonal.Edges()):
        if edge.geomType() != "LINE":
            continue
        vertices = edge.Vertices()
        if len(vertices) < 2:
            continue
        p0 = vertices[0].Center()
        p1 = vertices[-1].Center()
        dx, dy, dz = p1.x - p0.x, p1.y - p0.y, p1.z - p0.z
        chord = math.sqrt(dx * dx + dy * dy + dz * dz)
        if chord < 1.0e-9:
            continue
        midpoint = edge.Center()
        direction_y = dy / chord
        if (edge.Length() > 0.85 * math.hypot(bb.xlen, bb.zlen)
                and abs(direction_y) < 1.0e-5
                and abs(midpoint.y - bb.ymin) < 1.0e-4):
            candidates.append((edge.Length(), edge))

    if not candidates:
        raise ValueError("Could not locate the sharp longitudinal edge of SEC_01")

    target_edge = max(candidates, key=lambda item: item[0])[1]
    modified_diagonal = diagonal.fillet(6.349, [target_edge])
    if modified_diagonal is None or not modified_diagonal.isValid():
        raise RuntimeError("Unable to construct the requested R6.35 longitudinal fillet")

    output_solids = list(solids)
    output_solids[diagonal_index] = modified_diagonal
    result = cq.Compound.makeCompound(output_solids)

    if len(result.Solids()) != 3 or not result.isValid():
        raise RuntimeError("Edited assembly is invalid")

    return cq.Workplane("XY").newObject([result])