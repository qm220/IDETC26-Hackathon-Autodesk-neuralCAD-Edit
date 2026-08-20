def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    y_mid = 260.0

    reference_box = cq.Solid.makeBox(
        105.0, 70.0, 130.0,
        cq.Vector(-5.0, 190.0, -460.0)
    )
    reference_half = shape.intersect(reference_box)

    repaired_positive_half = reference_half.mirror(
        "XZ", cq.Vector(0.0, y_mid, 0.0)
    )

    replacement_box = cq.Solid.makeBox(
        105.0, 70.0, 130.0,
        cq.Vector(-5.0, y_mid, -460.0)
    )
    retained = shape.cut(replacement_box)
    final_shape = retained.fuse(repaired_positive_half)

    try:
        final_shape = final_shape.clean()
    except Exception:
        pass

    return cq.Workplane("XY").newObject([final_shape])