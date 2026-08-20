def my_cad_function(args):
    import os
    import cadquery as cq
    from OCP.gp import gp_Pnt, gp_Dir, gp_Ax2, gp_Trsf
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    original = model.val()

    if not original.isValid():
        raise RuntimeError("The imported STEP shape is invalid")

    bbox = original.BoundingBox()
    x_split = 100.0
    z_mid = 0.5 * (bbox.zmin + bbox.zmax)
    margin = max(10.0, 0.05 * max(bbox.xlen, bbox.ylen, bbox.zlen))

    region_x0 = bbox.xmin - margin
    region_y0 = bbox.ymin - margin
    region_dx = x_split - region_x0
    region_dy = bbox.ylen + 2.0 * margin

    lower_box = cq.Solid.makeBox(
        region_dx,
        region_dy,
        z_mid - (bbox.zmin - margin),
        cq.Vector(region_x0, region_y0, bbox.zmin - margin)
    )

    upper_box = cq.Solid.makeBox(
        region_dx,
        region_dy,
        (bbox.zmax + margin) - z_mid,
        cq.Vector(region_x0, region_y0, z_mid)
    )

    rounded_lower_reference = original.intersect(lower_box)
    if rounded_lower_reference.Volume() <= 0.0:
        raise RuntimeError("Could not isolate the rounded reference half")

    transform = gp_Trsf()
    transform.SetMirror(
        gp_Ax2(gp_Pnt(0.0, 0.0, z_mid), gp_Dir(0.0, 0.0, 1.0))
    )
    transformed = BRepBuilderAPI_Transform(
        rounded_lower_reference.wrapped, transform, True
    )
    transformed.Build()
    if not transformed.IsDone():
        raise RuntimeError("Could not mirror the existing rounded geometry")

    rounded_upper_patch = cq.Shape.cast(transformed.Shape())
    preserved_geometry = original.cut(upper_box)
    result_shape = preserved_geometry.fuse(rounded_upper_patch).clean()

    if not result_shape.isValid():
        raise RuntimeError("The reconstructed model is not a valid shape")

    solids = result_shape.Solids()
    if len(solids) != 1:
        raise RuntimeError(
            "Expected one connected solid after reconstruction, found %d" % len(solids)
        )

    return cq.Workplane(obj=result_shape)