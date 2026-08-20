def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    solids = list(shape.Solids())
    if not solids:
        raise ValueError("The imported model contains no solids.")

    expected_center = cq.Vector(-237.0, 340.0, 318.5)
    candidates = []
    for solid in solids:
        bb = solid.BoundingBox()
        c = solid.Center()
        if bb.xlen > 30.0 and bb.xlen > 3.0 * bb.ylen and 5.0 <= bb.ylen <= 16.0 and bb.zlen < 8.0:
            distance = ((c.x - expected_center.x) ** 2 + (c.y - expected_center.y) ** 2 + (c.z - expected_center.z) ** 2) ** 0.5
            candidates.append((distance, solid))

    if not candidates:
        raise ValueError("Could not identify the existing horizontal front-panel button.")

    candidates.sort(key=lambda item: item[0])
    existing_button = candidates[0][1]
    spacing = 28.0

    upper_button = existing_button.moved(cq.Location(cq.Vector(0.0, spacing, 0.0)))
    lower_button = existing_button.moved(cq.Location(cq.Vector(0.0, -spacing, 0.0)))

    edited_shape = cq.Compound.makeCompound(solids + [upper_button, lower_button])
    return cq.Workplane("XY").newObject([edited_shape])