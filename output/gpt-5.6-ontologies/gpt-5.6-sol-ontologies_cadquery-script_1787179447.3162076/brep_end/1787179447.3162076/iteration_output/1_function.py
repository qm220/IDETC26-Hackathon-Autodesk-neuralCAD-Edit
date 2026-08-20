def my_cad_function(args):
    import os
    import math
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()
    solids = list(shape.Solids())

    if len(solids) < 18:
        raise ValueError("Expected at least 18 solids, found %d" % len(solids))

    # Geometry identified from the imported STEP inspection:
    #   SOLID 0  = main coffeepot/appliance body
    #   SOLID 17 = external U-shaped handle/cradle
    pot = solids[0]
    handle_original = solids[17]

    # Remove a narrow clearance layer from only the handle. Translating the
    # pot radially in the X-Z cross-section and subtracting those copies is a
    # robust approximation of an outward offset of the pot surface. It avoids
    # changing the pot or any unrelated assembly component.
    clearance = float(args.get("clearance", 1.0))
    sample_count = 16
    handle = handle_original

    for i in range(sample_count):
        angle = 2.0 * math.pi * i / sample_count
        dx = clearance * math.cos(angle)
        dz = clearance * math.sin(angle)
        cutter = pot.translate((dx, 0.0, dz))
        handle = handle.cut(cutter)

    handle = handle.clean()
    if not handle.isValid():
        raise ValueError("Clearanced handle is not a valid shape")

    handle_solids = list(handle.Solids())
    if not handle_solids:
        raise ValueError("Clearance operation removed the entire handle")

    # Preserve every original solid except SOLID 17, which is replaced by its
    # locally clearanced result. Preserve all resulting pieces if a Boolean
    # operation happens to partition the handle.
    output_solids = solids[:17] + handle_solids + solids[18:]
    result = cq.Compound.makeCompound(output_solids)

    common = handle.intersect(pot)
    common_volume = common.Volume()
    removed_volume = handle_original.Volume() - handle.Volume()
    print("HANDLE_CLEARANCE requested=%.6f mm" % clearance)
    print("HANDLE volume_before=%.6f volume_after=%.6f removed=%.6f" % (
        handle_original.Volume(), handle.Volume(), removed_volume))
    print("HANDLE_POT common_volume=%.12f" % common_volume)
    print("RESULT valid=%s solids=%d" % (result.isValid(), len(result.Solids())))

    if common_volume > 1.0e-6:
        raise ValueError("Handle-to-pot interference remains: %.12f" % common_volume)

    return cq.Workplane("XY").newObject([result])