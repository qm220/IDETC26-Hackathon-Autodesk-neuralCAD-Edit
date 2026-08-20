def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported
    solids = list(root.Solids())

    if len(solids) <= 40:
        raise ValueError(
            "Expected the existing horizontal front-panel button at solid index 40, "
            "but the imported model contains only %d solids" % len(solids)
        )

    # Solid 40 is the existing left horizontal indicator/button identified by F-10.
    source_button = solids[40]
    bb = source_button.BoundingBox()
    width_x = bb.xmax - bb.xmin
    height_y = bb.ymax - bb.ymin
    depth_z = bb.zmax - bb.zmin

    if width_x <= height_y or depth_z >= width_x:
        raise ValueError(
            "Solid 40 does not have the expected shallow horizontal-button envelope: "
            "dx=%.3f, dy=%.3f, dz=%.3f" % (width_x, height_y, depth_z)
        )

    # In the imported model, X is horizontal, Y is vertical, and the front panel is
    # near constant Z. Use equal Y translations so the three button center points
    # form a vertical column. A 1.5-height pitch leaves a visible half-height gap.
    spacing = 1.5 * height_y

    upper_button = source_button.moved(cq.Location(cq.Vector(0, spacing, 0)))
    lower_button = source_button.moved(cq.Location(cq.Vector(0, -spacing, 0)))

    result = cq.Compound.makeCompound(solids + [upper_button, lower_button])

    center = bb.center
    print("Imported solids: %d" % len(solids))
    print(
        "Source button bbox: dx=%.3f, dy=%.3f, dz=%.3f"
        % (width_x, height_y, depth_z)
    )
    print(
        "Source button center: (%.3f, %.3f, %.3f)"
        % (center.x, center.y, center.z)
    )
    print("Equal vertical center spacing along Y: %.3f" % spacing)
    print(
        "Added exact translated copies at Y offsets %.3f and %.3f"
        % (spacing, -spacing)
    )
    return result