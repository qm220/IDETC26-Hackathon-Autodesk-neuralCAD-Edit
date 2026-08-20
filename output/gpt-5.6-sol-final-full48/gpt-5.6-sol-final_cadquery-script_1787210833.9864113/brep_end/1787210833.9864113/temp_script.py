def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported
    solids = list(root.Solids())

    if len(solids) < 8:
        raise ValueError("Expected the existing 12-solid scissor-lift assembly")

    # Solid indices identified in the supplied B-rep plan as the four long
    # transverse endpoint shafts. Preserve every other assembly solid.
    shaft_indices = (1, 3, 6, 7)
    updated_solids = list(solids)

    for index in shaft_indices:
        shaft = solids[index]
        bb = shaft.BoundingBox()

        # The endpoint shafts are coaxial with global Z. Their transverse
        # bounding dimensions recover the existing pin diameter without
        # changing the bearing shank.
        cx = 0.5 * (bb.xmin + bb.xmax)
        cy = 0.5 * (bb.ymin + bb.ymax)
        pin_diameter = min(bb.xlen, bb.ylen)

        # A common head proportion gives overlap beyond the pivot bore while
        # remaining comfortably within the surrounding link-end boss.
        head_diameter = 1.45 * pin_diameter
        head_radius = 0.5 * head_diameter
        head_thickness = max(0.22 * pin_diameter, 0.8)

        rear_head = cq.Solid.makeCylinder(
            head_radius,
            head_thickness,
            cq.Vector(cx, cy, bb.zmin),
            cq.Vector(0, 0, -1),
        )
        front_head = cq.Solid.makeCylinder(
            head_radius,
            head_thickness,
            cq.Vector(cx, cy, bb.zmax),
            cq.Vector(0, 0, 1),
        )

        headed_shaft = shaft.fuse(rear_head, front_head)
        updated_solids[index] = headed_shaft

        print(
            "Added two cylindrical retaining heads to shaft {} at "
            "({:.3f}, {:.3f}); diameter {:.3f}, thickness {:.3f}".format(
                index, cx, cy, head_diameter, head_thickness
            )
        )

    result = cq.Compound.makeCompound(updated_solids)
    print("Retained all original components and added eight endpoint-pin heads.")
    return result