def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    solids = list(shape.Solids())
    if not solids:
        raise ValueError("The imported model contains no solids.")

    # Locate the existing horizontal front-panel button by its known spatial
    # and dimensional characteristics rather than relying only on its index.
    expected_center = cq.Vector(-237.0, 340.0, 318.5)
    candidates = []
    for solid in solids:
        bb = solid.BoundingBox()
        c = solid.Center()
        dx = bb.xlen
        dy = bb.ylen
        dz = bb.zlen

        # Existing button is an elongated horizontal solid approximately
        # 43 x 10 x 4.8 mm on the upper/front control panel.
        if dx > 30.0 and dx > 3.0 * dy and 5.0 <= dy <= 16.0 and dz < 8.0:
            distance = (
                (c.x - expected_center.x) ** 2
                + (c.y - expected_center.y) ** 2
                + (c.z - expected_center.z) ** 2
            ) ** 0.5
            candidates.append((distance, solid))

    if not candidates:
        raise ValueError("Could not identify the existing horizontal front-panel button.")

    candidates.sort(key=lambda item: item[0])
    existing_button = candidates[0][1]
    existing_center = existing_button.Center()
    existing_bb = existing_button.BoundingBox()

    # Equal center-to-center spacing gives equal clear gaps because both new
    # buttons are exact geometric copies of the existing button.
    spacing = 28.0
    upper_button = existing_button.moved(
        cq.Location(cq.Vector(0.0, spacing, 0.0))
    )
    lower_button = existing_button.moved(
        cq.Location(cq.Vector(0.0, -spacing, 0.0))
    )

    # Preserve every original solid, including the unchanged source button,
    # and append exactly two copied button solids.
    edited_shape = cq.Compound.makeCompound(solids + [upper_button, lower_button])

    print("Existing button center=(%.3f, %.3f, %.3f), size=(%.3f, %.3f, %.3f)" % (
        existing_center.x, existing_center.y, existing_center.z,
        existing_bb.xlen, existing_bb.ylen, existing_bb.zlen
    ))
    print("Upper copy center=(%.3f, %.3f, %.3f)" % (
        upper_button.Center().x, upper_button.Center().y, upper_button.Center().z
    ))
    print("Lower copy center=(%.3f, %.3f, %.3f)" % (
        lower_button.Center().x, lower_button.Center().y, lower_button.Center().z
    ))
    print("Original solids=%d; edited solids=%d; equal spacing=%.3f" % (
        len(solids), len(edited_shape.Solids()), spacing
    ))

    return cq.Workplane("XY").newObject([edited_shape])