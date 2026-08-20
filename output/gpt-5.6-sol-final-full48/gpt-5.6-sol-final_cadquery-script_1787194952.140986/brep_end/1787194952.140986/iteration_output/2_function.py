def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()
    solids = list(shape.Solids())

    if len(solids) < 2:
        raise ValueError("Expected the sprocket body and separate center insert as distinct solids")

    def radial_extent(s):
        bb = s.BoundingBox()
        return max(abs(bb.xmin), abs(bb.xmax), abs(bb.zmin), abs(bb.zmax))

    insert_index = min(range(len(solids)), key=lambda i: radial_extent(solids[i]))
    insert = solids[insert_index]
    ibb = insert.BoundingBox()

    front_y = ibb.ymax
    outer_r = radial_extent(insert)
    chamfer = 1.0
    eps = 0.01

    cutter_start = front_y - chamfer - eps
    cutter_height = chamfer + 2.0 * eps
    cutter_outer_r = outer_r + 2.0

    outer_cutter = cq.Solid.makeCylinder(
        cutter_outer_r,
        cutter_height,
        cq.Vector(0, cutter_start, 0),
        cq.Vector(0, 1, 0)
    )
    retained_cone = cq.Solid.makeCone(
        outer_r + eps,
        outer_r - chamfer - eps,
        cutter_height,
        cq.Vector(0, cutter_start, 0),
        cq.Vector(0, 1, 0)
    )
    annular_cutter = outer_cutter.cut(retained_cone)
    edited_insert = insert.cut(annular_cutter)

    if not edited_insert.isValid():
        raise ValueError("The center-insert chamfer operation produced an invalid solid")

    result_solids = [
        edited_insert if i == insert_index else solid
        for i, solid in enumerate(solids)
    ]

    result_shape = cq.Compound.makeCompound(result_solids)
    result = cq.Workplane("XZ").newObject([result_shape])

    print("EDIT: replaced front-center insert transition with 1 mm x 45 degree chamfer")
    print("RESULT VALID:", result_shape.isValid())
    print("RESULT SOLIDS:", len(result_shape.Solids()))

    return result