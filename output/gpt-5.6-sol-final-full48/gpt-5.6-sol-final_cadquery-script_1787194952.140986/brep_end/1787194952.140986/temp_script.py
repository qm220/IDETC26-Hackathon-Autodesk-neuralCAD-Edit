def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()
    solids = list(shape.Solids())

    if len(solids) < 2:
        raise ValueError("Expected the sprocket body and separate center insert as distinct solids")

    # Identify the separate center insert by its substantially smaller radial extent.
    def radial_extent(s):
        bb = s.BoundingBox()
        return max(abs(bb.xmin), abs(bb.xmax), abs(bb.zmin), abs(bb.zmax))

    insert_index = min(range(len(solids)), key=lambda i: radial_extent(solids[i]))
    insert = solids[insert_index]
    ibb = insert.BoundingBox()

    # The imported part lies in the XZ plane and its front is the maximum-Y side.
    # Replace the existing narrow rounded/beveled outer transition of the raised
    # center insert with an equal-distance 1 mm x 45 degree chamfer.  The cutter
    # limits the insert radius linearly over the final 1 mm of axial height.
    front_y = ibb.ymax
    outer_r = radial_extent(insert)
    chamfer = 1.0

    # Small overtravel avoids coincident Boolean faces while retaining the exact
    # 1:1 radial/axial chamfer at the nominal insert surfaces.
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

    result_solids = []
    for i, solid in enumerate(solids):
        result_solids.append(edited_insert if i == insert_index else solid)

    result_shape = cq.Compound.makeCompound(result_solids)
    result = cq.Workplane("XZ").newObject([result_shape])

    rbb = result_shape.BoundingBox()
    print("EDIT: replaced front-center insert transition with 1 mm x 45 degree chamfer")
    print("INSERT INDEX:", insert_index)
    print("FRONT Y:", front_y, "OUTER RADIUS:", outer_r)
    print("RESULT VALID:", result_shape.isValid())
    print("RESULT SOLIDS:", len(result_shape.Solids()))
    print("RESULT BBOX:", rbb.xmin, rbb.xmax, rbb.ymin, rbb.ymax, rbb.zmin, rbb.zmax)

    return result