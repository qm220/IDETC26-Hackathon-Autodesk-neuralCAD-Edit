def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    root = model.val() if hasattr(model, "val") else model
    solids = list(root.Solids())

    if len(solids) != 9:
        raise ValueError(f"Expected 9 solids in the imported model, found {len(solids)}")

    # SOLID 3 is the Heatbreak / filament throat tube. Its dominant outer
    # cylindrical section has radius 3.45 mm and extends from Z=7.5 to 20.8 mm.
    # The existing top chamfer reduces that radius by 0.2 mm over 0.2 mm of
    # axial height, so the requested matching lower chamfer is 0.2 mm.
    heatbreak = solids[3]
    target_edges = []

    for edge in heatbreak.Edges():
        if edge.geomType() != "CIRCLE":
            continue
        try:
            radius = edge.radius()
            center = edge.Center()
        except Exception:
            continue

        if (
            abs(radius - 3.45) < 1.0e-4
            and abs(center.x) < 1.0e-4
            and abs(center.y + 40.0) < 1.0e-4
            and abs(center.z - 7.5) < 1.0e-4
        ):
            target_edges.append(edge)

    print(f"Heatbreak lower main-cylinder edges found: {len(target_edges)}")
    if len(target_edges) != 1:
        raise ValueError(
            "Could not uniquely identify the circular lower edge of the "
            "Heatbreak's radius-3.45 mm main cylinder at Z=7.5 mm"
        )

    # Retain the imported solid as the context body while placing only the
    # intended circular edge on the active stack for the chamfer operation.
    heatbreak_wp = cq.Workplane(obj=heatbreak)
    edited_heatbreak = heatbreak_wp.newObject(target_edges).chamfer(0.2).val()

    if not edited_heatbreak.isValid():
        raise ValueError("The chamfered Heatbreak solid is invalid")

    # Replace only SOLID 3 and preserve every other imported component.
    output_solids = list(solids)
    output_solids[3] = edited_heatbreak
    result = cq.Compound.makeCompound(output_solids)

    print(f"Result valid: {result.isValid()}")
    print(f"Result solids: {len(result.Solids())}")
    print(f"Original Heatbreak volume: {heatbreak.Volume():.6f}")
    print(f"Edited Heatbreak volume: {edited_heatbreak.Volume():.6f}")

    # Report the expected new conical lead-in surface near the lower edge.
    for i, face in enumerate(edited_heatbreak.Faces()):
        if face.geomType() == "CONE":
            bb = face.BoundingBox()
            if bb.zmin >= 7.49 and bb.zmax <= 7.71:
                cone = face._geomAdaptor().Cone()
                print(
                    f"New lower chamfer face {i}: "
                    f"z=({bb.zmin:.6f},{bb.zmax:.6f}), "
                    f"semi_angle={cone.SemiAngle():.8f}"
                )

    return cq.Workplane(obj=result)