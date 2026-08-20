def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    source = cq.importers.importStep(input_file)
    source_shape = source.val()

    print("SOURCE VALID:", source_shape.isValid())
    print("SOURCE FACES:", len(source_shape.Faces()), "EDGES:", len(source_shape.Edges()))
    for i, face in enumerate(source_shape.Faces()):
        bb = face.BoundingBox()
        c = face.Center()
        print("FACE %d type=%s center=(%.3f,%.3f,%.3f) bbox=(%.3f..%.3f, %.3f..%.3f, %.3f..%.3f)" % (
            i, face.geomType(), c.x, c.y, c.z,
            bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax
        ))

    def shape_wp(shape):
        return cq.Workplane("XY").newObject([shape])

    # Reconstruct the sharp design envelope to remove every source chamfer
    # and fillet. FACE 34 was the protruding lower surface at z=-450, while
    # adjacent shank FACE 12 was at z=-445. The common lower level is -445.
    z_bottom = -445.0
    z_top = -340.0
    thickness = z_top - z_bottom

    # Directly construct the plan boundary with the requested replacement
    # radii. The two concave transitions at x=100, where the 120 mm-wide end
    # meets the 60 mm-wide shank, are R20. Every other plan corner is R5.
    # Explicit arcs replace the unavailable Workplane.fillet2D operation.
    profile = (
        cq.Workplane("XY", origin=(0.0, 0.0, z_bottom))
        .moveTo(5.0, 200.0)
        .lineTo(95.0, 200.0)
        .threePointArc((98.535534, 201.464466), (100.0, 205.0))
        .lineTo(100.0, 210.0)
        .threePointArc((105.857864, 224.142136), (120.0, 230.0))
        .lineTo(295.0, 230.0)
        .threePointArc((298.535534, 231.464466), (300.0, 235.0))
        .lineTo(300.0, 285.0)
        .threePointArc((298.535534, 288.535534), (295.0, 290.0))
        .lineTo(120.0, 290.0)
        .threePointArc((105.857864, 295.857864), (100.0, 310.0))
        .lineTo(100.0, 315.0)
        .threePointArc((98.535534, 318.535534), (95.0, 320.0))
        .lineTo(5.0, 320.0)
        .threePointArc((1.464466, 318.535534), (0.0, 315.0))
        .lineTo(0.0, 205.0)
        .threePointArc((1.464466, 201.464466), (5.0, 200.0))
        .close()
    )

    outer = profile.extrude(thickness).val()
    if not outer.isValid():
        raise ValueError("The replacement outer envelope is invalid")

    # The remaining top and bottom boundary edges are all in the R5 class.
    top_bottom_edges = []
    for edge in outer.Edges():
        bb = edge.BoundingBox()
        c = edge.Center()
        if bb.zlen < 1.0e-5 and (
            abs(c.z - z_bottom) < 1.0e-4 or
            abs(c.z - z_top) < 1.0e-4
        ):
            top_bottom_edges.append(edge)

    print("OUTER R5 TOP/BOTTOM EDGES:", len(top_bottom_edges))
    if not top_bottom_edges:
        raise ValueError("No top or bottom perimeter edges were found")
    outer = shape_wp(outer).newObject(top_bottom_edges).fillet(5.0).val()

    if not outer.isValid():
        raise ValueError("Outer body became invalid after R5 edge fillets")

    # Restore F002: longitudinal blind bore, grounded from source FACE 20.
    # Extend the cutter through the x=300 opening. Radius the blind-end cutter
    # edge first so subtraction leaves an internal R5 bottom transition.
    bore_radius = 14.142135623730951
    bore_cutter = cq.Solid.makeCylinder(
        bore_radius,
        205.0,
        cq.Vector(100.0, 270.0, -400.0),
        cq.Vector(1.0, 0.0, 0.0)
    )

    blind_edges = []
    for edge in bore_cutter.Edges():
        c = edge.Center()
        if edge.geomType() == "CIRCLE" and abs(c.x - 100.0) < 1.0e-4:
            blind_edges.append(edge)
    print("BORE BLIND-END R5 EDGES:", len(blind_edges))
    if len(blind_edges) != 1:
        raise ValueError("The bore blind-end edge was not uniquely grounded")
    bore_cutter = shape_wp(bore_cutter).newObject(blind_edges).fillet(5.0).val()

    result = outer.cut(bore_cutter)

    # Apply R5 to the circular bore mouth, which is an 'other edge'.
    mouth_edges = []
    for edge in result.Edges():
        c = edge.Center()
        if (edge.geomType() == "CIRCLE" and
            abs(c.x - 300.0) < 1.0e-3 and
            abs(c.y - 270.0) < 1.0e-2 and
            abs(c.z + 400.0) < 1.0e-2):
            mouth_edges.append(edge)
    print("BORE MOUTH R5 EDGES:", len(mouth_edges))
    if len(mouth_edges) != 1:
        raise ValueError("The bore-mouth edge was not uniquely grounded")
    result = shape_wp(result).newObject(mouth_edges).fillet(5.0).val()

    # Restore F003. A fully R5-rounded rectangular cutter gives R5 to all
    # pocket edges. It begins outside the y=230 wall so the pocket remains
    # open on that side and terminates at the grounded y=280 blind wall.
    pocket_x0 = 125.350920
    pocket_x1 = 168.336333
    pocket_z0 = -405.071245
    pocket_z1 = -374.121747
    pocket_cutter = cq.Solid.makeBox(
        pocket_x1 - pocket_x0,
        55.0,
        pocket_z1 - pocket_z0,
        cq.Vector(pocket_x0, 225.0, pocket_z0)
    )
    pocket_edges = list(pocket_cutter.Edges())
    print("POCKET CUTTER R5 EDGES:", len(pocket_edges))
    pocket_cutter = shape_wp(pocket_cutter).newObject(pocket_edges).fillet(5.0).val()
    result = result.cut(pocket_cutter).clean()

    if not result.isValid():
        raise ValueError("Final reconstructed solid is invalid")
    if len(result.Solids()) != 1:
        raise ValueError("Final result is not a single solid")

    bb = result.BoundingBox()
    print("FINAL VALID:", result.isValid())
    print("FINAL SOLIDS:", len(result.Solids()))
    print("FINAL FACES:", len(result.Faces()), "EDGES:", len(result.Edges()))
    print("FINAL BBOX:", (bb.xmin, bb.ymin, bb.zmin), (bb.xmax, bb.ymax, bb.zmax))
    print("FINAL VOLUME:", result.Volume())
    print("COPLANAR LOWER SURFACE Z:", z_bottom)
    print("JUNCTION RADII: R20; ALL OTHER MODELED EDGES: R5")

    return cq.Workplane("XY").newObject([result])