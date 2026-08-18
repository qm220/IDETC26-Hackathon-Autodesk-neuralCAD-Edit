def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    source = cq.importers.importStep(input_file).val()
    bb = source.BoundingBox()

    head_junction_x = bb.xmin + 100.0
    thickness_mid_z = 0.5 * (bb.zmin + bb.zmax)
    margin = 10.0

    lower_head_box = cq.Solid.makeBox(
        head_junction_x - bb.xmin + margin,
        bb.ylen + 2.0 * margin,
        thickness_mid_z - bb.zmin + margin,
        cq.Vector(bb.xmin - margin, bb.ymin - margin, bb.zmin - margin)
    )
    radiused_half = source.intersect(lower_head_box)

    mirrored_half = radiused_half.mirror(
        "XY", cq.Vector(0.0, 0.0, thickness_mid_z)
    )

    sharp_half_removal = cq.Solid.makeBox(
        head_junction_x - bb.xmin + margin,
        bb.ylen + 2.0 * margin,
        bb.zmax - thickness_mid_z + margin,
        cq.Vector(bb.xmin - margin, bb.ymin - margin, thickness_mid_z)
    )
    retained = source.cut(sharp_half_removal)
    result = retained.fuse(mirrored_half).clean()

    print("Source valid:", source.isValid())
    print("Result valid:", result.isValid())
    print("Result solids:", len(result.Solids()))
    print("Thickness midplane z:", thickness_mid_z)
    print("Head/arm junction x:", head_junction_x)
    print("Source volume:", round(source.Volume(), 6))
    print("Result volume:", round(result.Volume(), 6))

    if not result.isValid() or len(result.Solids()) != 1:
        raise ValueError("Mirrored head-radius reconstruction did not produce one valid solid")

    return cq.Workplane(obj=result)