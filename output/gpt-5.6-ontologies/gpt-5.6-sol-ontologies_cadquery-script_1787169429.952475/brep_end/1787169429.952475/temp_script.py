def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    original = model.val()

    # T01: Enlarge the coaxial bores in the paired clevis ears to form a
    # transverse connecting-pin hole of exactly 1.7 mm diameter.
    pin_center_y = 3.510000
    pin_center_z = 2.943179
    pin_radius = 1.7 / 2.0
    pin_cutter = cq.Solid.makeCylinder(
        pin_radius,
        3.10,
        cq.Vector(4.60, pin_center_y, pin_center_z),
        cq.Vector(1, 0, 0)
    )
    result = original.cut(pin_cutter)

    # T02: Add multiple circumferential grip grooves to the mounting contact
    # face. The ambiguous 0.1 mm groove dimension is implemented as both
    # groove width and groove depth. One groove surrounds each mounting hole.
    mounting_centers = [
        (0.293627, 1.473530),
        (0.293627, -1.526470),
        (11.953627, 1.123530),
        (11.953627, -2.986470),
    ]
    groove_inner_radius = 0.58
    groove_width = 0.10
    groove_outer_radius = groove_inner_radius + groove_width
    groove_depth = 0.10
    mounting_face_y = -0.0100

    for x, z in mounting_centers:
        outer = cq.Solid.makeCylinder(
            groove_outer_radius,
            groove_depth + 0.001,
            cq.Vector(x, mounting_face_y - 0.0005, z),
            cq.Vector(0, 1, 0)
        )
        inner = cq.Solid.makeCylinder(
            groove_inner_radius,
            groove_depth + 0.001,
            cq.Vector(x, mounting_face_y - 0.0005, z),
            cq.Vector(0, 1, 0)
        )
        annular_groove = outer.cut(inner)
        result = result.cut(annular_groove)

    final_model = cq.Workplane("XY").newObject([result])

    bb = result.BoundingBox()
    print("FINAL valid=%s solids=%d faces=%d volume=%.6f" % (
        result.isValid(), len(result.Solids()), len(result.Faces()), result.Volume()))
    print("FINAL bbox min=(%.4f, %.4f, %.4f) max=(%.4f, %.4f, %.4f)" % (
        bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax))
    print("CONNECTING HOLE diameter=%.4f axis=X center_y=%.6f center_z=%.6f" % (
        2.0 * pin_radius, pin_center_y, pin_center_z))
    print("GRIP GROOVES count=%d width=%.4f depth=%.4f inner_radius=%.4f outer_radius=%.4f" % (
        len(mounting_centers), groove_width, groove_depth,
        groove_inner_radius, groove_outer_radius))

    return final_model