def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported
    solids = list(root.Solids())

    if len(solids) <= 40:
        raise ValueError("Expected source button at solid index 40, but the imported model contains only %d solids" % len(solids))

    # Feature F-10 is owned by solid 40 according to the supplied B-rep plan.
    source_button = solids[40]
    bb = source_button.BoundingBox()
    width_x = bb.xmax - bb.xmin
    depth_y = bb.ymax - bb.ymin
    height_z = bb.zmax - bb.zmin

    # Confirm that the selected component has the expected horizontal pill-like envelope.
    if width_x <= height_z:
        raise ValueError(
            "Solid 40 does not have the expected horizontal-button proportions: "
            "dx=%.3f, dy=%.3f, dz=%.3f" % (width_x, depth_y, height_z)
        )

    # Three button heights gives a balanced pitch while leaving a clear gap between
    # adjacent identical buttons. Both copies use exactly the same pitch.
    spacing = 3.0 * height_z

    upper_button = source_button.moved(cq.Location(cq.Vector(0, 0, -spacing)))
    lower_button = source_button.moved(cq.Location(cq.Vector(0, 0, spacing)))

    result = cq.Compound.makeCompound(solids + [upper_button, lower_button])

    center = bb.center
    print("Imported solids: %d" % len(solids))
    print("Source button bbox: dx=%.3f, dy=%.3f, dz=%.3f" % (width_x, depth_y, height_z))
    print("Source button center: (%.3f, %.3f, %.3f)" % (center.x, center.y, center.z))
    print("Equal vertical center spacing: %.3f" % spacing)
    print("Added exact translated copies at Z offsets %.3f and %.3f" % (-spacing, spacing))
    return result