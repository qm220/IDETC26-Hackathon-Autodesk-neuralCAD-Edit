def my_cad_function(args):
    import os
    import math
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

    def as_wp(shape):
        return cq.Workplane("XY").newObject([shape])

    # Grounding from the inspected STEP:
    # FACE 34 is the protruding enlarged-end lower face at z=-450.
    # Adjacent shank FACE 12 is at z=-445. Rebuild the enlarged end with its
    # lower surface at z=-445, making the two surfaces coplanar.
    z_bottom = -445.0
    z_top = -340.0
    body_height = z_top - z_bottom

    # Reconstruct the unchamfered outer envelope. This removes all original
    # F004 chamfers and all original F005/F007/F008 radii. The plan is made
    # symmetric about y=260 for the enlarged portion and y=260 for the shank.
    # The two shoulder transitions where the large and narrow portions meet
    # are R20. Remaining plan corners are R5.
    profile = (
        cq.Workplane("XY", origin=(0.0, 0.0, z_bottom))
        .moveTo(5.0, 200.0)
        .lineTo(95.0, 200.0)
        .threePointArc((98.535533906, 201.464466094), (100.0, 205.0))
        .lineTo(100.0, 210.0)
        .threePointArc((105.857864376, 224.142135624), (120.0, 230.0))
        .lineTo(295.0, 230.0)
        .threePointArc((298.535533906, 231.464466094), (300.0, 235.0))
        .lineTo(300.0, 285.0)
        .threePointArc((298.535533906, 288.535533906), (295.0, 290.0))
        .lineTo(120.0, 290.0)
        .threePointArc((105.857864376, 295.857864376), (100.0, 310.0))
        .lineTo(100.0, 315.0)
        .threePointArc((98.535533906, 318.535533906), (95.0, 320.0))
        .lineTo(5.0, 320.0)
        .threePointArc((1.464466094, 318.535533906), (0.0, 315.0))
        .lineTo(0.0, 205.0)
        .threePointArc((1.464466094, 201.464466094), (5.0, 200.0))
        .close()
    )

    outer = profile.extrude(body_height).val()
    if not outer.isValid():
        raise ValueError("Sharp replacement envelope is invalid")

    # All top and bottom perimeter edges are in the R5 class. Applying these
    # together produces R5 rounds through the thickness while retaining the
    # R20 shoulder cylinders in the middle of the body height.
    perimeter_edges = []
    for edge in outer.Edges():
        bb = edge.BoundingBox()
        c = edge.Center()
        if bb.zlen < 1.0e-6 and (
            abs(c.z - z_bottom) < 1.0e-5 or
            abs(c.z - z_top) < 1.0e-5
        ):
            perimeter_edges.append(edge)

    print("OUTER TOP/BOTTOM R5 EDGES:", len(perimeter_edges))
    if len(perimeter_edges) == 0:
        raise ValueError("No outer top/bottom edges were identified")

    outer = as_wp(outer).newObject(perimeter_edges).fillet(5.0).val()
    if not outer.isValid():
        raise ValueError("Outer body is invalid after R5 fillets")

    # Restore F002 using a purpose-built revolved cutter. Its profile includes
    # R5 transitions at both the blind bottom and the bore mouth, avoiding the
    # unreliable post-boolean circular-edge fillet from the previous attempt.
    bore_r = 14.142135623730951
    fillet_r = 5.0
    inner_r = bore_r - fillet_r
    outer_r = bore_r + fillet_r
    s = fillet_r / math.sqrt(2.0)

    bore_profile = (
        cq.Workplane("XZ", origin=(0.0, 270.0, -400.0))
        .moveTo(100.0, 0.0)
        .lineTo(100.0, inner_r)
        .threePointArc((105.0 - s, inner_r + s), (105.0, bore_r))
        .lineTo(295.0, bore_r)
        .threePointArc((295.0 + s, outer_r - s), (300.0, outer_r))
        .lineTo(305.0, outer_r)
        .lineTo(305.0, 0.0)
        .close()
    )
    bore_cutter = bore_profile.revolve(
        360.0, (0.0, 0.0), (1.0, 0.0), combine=False
    ).val()

    if not bore_cutter.isValid():
        raise ValueError("Revolved R5 bore cutter is invalid")

    result = outer.cut(bore_cutter)
    if not result.isValid():
        raise ValueError("Body is invalid after bore subtraction")

    # Restore F003. Filleting every edge of the cutter before subtraction
    # creates R5 transitions on the pocket walls, blind wall, and opening.
    pocket_x0 = 125.350920
    pocket_x1 = 168.336333
    pocket_z0 = -405.071245
    pocket_z1 = -374.121747

    pocket_box = cq.Solid.makeBox(
        pocket_x1 - pocket_x0,
        60.0,
        pocket_z1 - pocket_z0,
        cq.Vector(pocket_x0, 220.0, pocket_z0)
    )
    pocket_edges = list(pocket_box.Edges())
    print("POCKET CUTTER R5 EDGES:", len(pocket_edges))
    pocket_cutter = as_wp(pocket_box).newObject(pocket_edges).fillet(5.0).val()

    if not pocket_cutter.isValid():
        raise ValueError("R5 pocket cutter is invalid")

    result = result.cut(pocket_cutter).clean()

    if not result.isValid():
        raise ValueError("Final reconstructed solid is invalid")
    if len(result.Solids()) != 1:
        raise ValueError("Final result is not one solid")

    bb = result.BoundingBox()
    print("FINAL VALID:", result.isValid())
    print("FINAL SOLIDS:", len(result.Solids()))
    print("FINAL FACES:", len(result.Faces()), "EDGES:", len(result.Edges()))
    print("FINAL BBOX:", (bb.xmin, bb.ymin, bb.zmin), (bb.xmax, bb.ymax, bb.zmax))
    print("FINAL VOLUME:", result.Volume())
    print("LOWER SURFACES COPLANAR AT Z:", z_bottom)
    print("SHOULDER TRANSITIONS: R20")
    print("OTHER RECONSTRUCTED EDGES: R5")

    return cq.Workplane("XY").newObject([result])