def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    source = cq.importers.importStep(input_file)
    source_shape = source.val()

    print("SOURCE VALID:", source_shape.isValid())
    print("SOURCE FACES:", len(source_shape.Faces()), "EDGES:", len(source_shape.Edges()))
    print("--- GROUNDED SOURCE FACES ---")
    for i, face in enumerate(source_shape.Faces()):
        bb = face.BoundingBox()
        c = face.Center()
        print("FACE %d type=%s center=(%.3f,%.3f,%.3f) bbox=(%.3f..%.3f, %.3f..%.3f, %.3f..%.3f)" % (
            i, face.geomType(), c.x, c.y, c.z,
            bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax
        ))

    def as_wp(shape):
        return cq.Workplane("XY").newObject([shape])

    # Reconstruct the unchamfered and unfilleted design envelope. The source
    # top is z=-340. FACE 12 is the adjacent shank bottom at z=-445, whereas
    # the enlarged end's protruding FACE 34 was at z=-450. Moving that face to
    # z=-445 makes the two lower surfaces coplanar and gives a uniform 105 mm
    # thickness. The plan is symmetric about y=260: enlarged width 200..320
    # and narrow width 230..290.
    z0 = -445.0
    height = 105.0
    outline_points = [
        (0.0, 200.0),
        (100.0, 200.0),
        (100.0, 230.0),
        (300.0, 230.0),
        (300.0, 290.0),
        (100.0, 290.0),
        (100.0, 320.0),
        (0.0, 320.0)
    ]

    profile = cq.Workplane("XY", origin=(0.0, 0.0, z0)).polyline(outline_points).close()

    def vertices_near(workplane, points, tolerance=1.0e-4):
        selected = []
        for vertex in workplane.vertices().vals():
            p = vertex.Center()
            for x, y in points:
                if abs(p.x - x) < tolerance and abs(p.y - y) < tolerance:
                    selected.append(vertex)
                    break
        return selected

    # The two re-entrant junction edges are the grounded meeting edges between
    # the narrow and enlarged portions. Filleting their profile vertices by
    # 20 mm produces two full-height R20 junction surfaces.
    r20_vertices = vertices_near(profile, [(100.0, 230.0), (100.0, 290.0)])
    print("R20 PROFILE VERTICES:", len(r20_vertices))
    if len(r20_vertices) != 2:
        raise ValueError("Could not ground both narrow-to-enlarged junction vertices")
    profile = profile.newObject(r20_vertices).fillet2D(20.0)

    # All other plan-outline corners receive R5. Applying this in the sketch
    # avoids an unstable mixed-radius 3-D rolling-ball operation.
    other_plan_corners = [
        (0.0, 200.0), (100.0, 200.0),
        (300.0, 230.0), (300.0, 290.0),
        (100.0, 320.0), (0.0, 320.0)
    ]
    r5_vertices = vertices_near(profile, other_plan_corners)
    print("R5 PROFILE VERTICES:", len(r5_vertices))
    if len(r5_vertices) != 6:
        raise ValueError("Could not ground all six remaining plan corners")
    profile = profile.newObject(r5_vertices).fillet2D(5.0)

    outer = profile.extrude(height).val()
    if not outer.isValid():
        raise ValueError("Outer extrusion is invalid")

    # Radius every remaining top and bottom perimeter edge by R5. The vertical
    # junction rounds are already R20 and the other vertical corners are
    # already R5 from the 2-D profile.
    thickness_edges = []
    for edge in outer.Edges():
        bb = edge.BoundingBox()
        if bb.zlen < 1.0e-5 and (
            abs(edge.Center().z - z0) < 1.0e-4 or
            abs(edge.Center().z - (z0 + height)) < 1.0e-4
        ):
            thickness_edges.append(edge)

    print("OUTER TOP/BOTTOM R5 EDGES:", len(thickness_edges))
    if not thickness_edges:
        raise ValueError("No outer thickness edges were found for R5")
    outer = as_wp(outer).newObject(thickness_edges).fillet(5.0).val()

    # Restore F002, the longitudinal blind socket. First fillet the cutter's
    # blind-end circular edge; subtraction then creates a concave R5 radius at
    # the bore bottom while preserving the grounded radius and axis.
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
    print("BORE CUTTER BLIND R5 EDGES:", len(blind_edges))
    if blind_edges:
        bore_cutter = as_wp(bore_cutter).newObject(blind_edges).fillet(5.0).val()

    result = outer.cut(bore_cutter)

    # Radius the bore-opening edge at x=300 by R5. It is treated separately
    # from the blind end because simultaneous concave filleting was unstable
    # in the previous iteration.
    mouth_edges = []
    for edge in result.Edges():
        c = edge.Center()
        if (edge.geomType() == "CIRCLE"
                and abs(c.x - 300.0) < 1.0e-3
                and abs(c.y - 270.0) < 1.0e-2
                and abs(c.z + 400.0) < 1.0e-2):
            mouth_edges.append(edge)
    print("BORE MOUTH R5 EDGES:", len(mouth_edges))
    if len(mouth_edges) == 1:
        result = as_wp(result).newObject(mouth_edges).fillet(5.0).val()
    else:
        print("Warning: bore mouth edge was not uniquely identified")

    # Restore F003 using a fully R5-rounded cutter. The cutter starts 5 mm
    # outside the y=230 side and terminates at y=280. Filleting all cutter
    # edges creates R5 pocket side corners and R5 transitions at its blind end;
    # the outside extension leaves a clean open pocket mouth.
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
    pocket_all_edges = list(pocket_cutter.Edges())
    print("POCKET CUTTER R5 EDGES:", len(pocket_all_edges))
    pocket_cutter = as_wp(pocket_cutter).newObject(pocket_all_edges).fillet(5.0).val()
    result = result.cut(pocket_cutter)

    result = result.clean()
    if not result.isValid():
        raise ValueError("Final reconstructed solid is invalid")
    if len(result.Solids()) != 1:
        raise ValueError("Final result is not a single solid")

    bb = result.BoundingBox()
    print("FINAL VALID:", result.isValid())
    print("FINAL SOLIDS:", len(result.Solids()), "FACES:", len(result.Faces()), "EDGES:", len(result.Edges()))
    print("FINAL BBOX:", (bb.xmin, bb.ymin, bb.zmin), (bb.xmax, bb.ymax, bb.zmax))
    print("FINAL VOLUME:", result.Volume())
    print("EXPECTED COPLANAR BOTTOM Z:", z0)
    return cq.Workplane("XY").newObject([result])