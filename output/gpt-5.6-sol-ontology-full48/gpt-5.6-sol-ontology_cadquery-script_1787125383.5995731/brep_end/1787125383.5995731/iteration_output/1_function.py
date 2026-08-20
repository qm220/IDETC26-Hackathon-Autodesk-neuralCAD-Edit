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

    # Reconstruct the feature history without the source chamfers and fillets.
    # The enlarged region is symmetric about y=260.  The stepped shank side is
    # moved to y=290, opposite y=230, making the exterior shank symmetric about
    # the same plane.
    enlarged = cq.Solid.makeBox(
        100.0, 120.0, 110.0, cq.Vector(0.0, 200.0, -450.0)
    )
    shank = cq.Solid.makeBox(
        200.0, 60.0, 105.0, cq.Vector(100.0, 230.0, -445.0)
    )
    outer = enlarged.fuse(shank)

    def wp(s):
        return cq.Workplane("XY").newObject([s])

    def is_line(edge):
        try:
            return edge.geomType() == "LINE"
        except Exception:
            return False

    def is_vertical(edge, tol=1.0e-5):
        bb = edge.BoundingBox()
        return (bb.xlen < tol and bb.ylen < tol and bb.zlen > 1.0)

    # R20 applies to the two straight junction edges running through the part
    # thickness at the narrow/enlarged meeting area x=100.
    junction_edges = []
    for edge in outer.Edges():
        c = edge.Center()
        if (is_line(edge) and is_vertical(edge)
                and abs(c.x - 100.0) < 1.0e-4
                and (abs(c.y - 230.0) < 1.0e-4 or abs(c.y - 290.0) < 1.0e-4)):
            junction_edges.append(edge)

    print("R20 JUNCTION EDGES:", len(junction_edges))
    if len(junction_edges) != 2:
        raise ValueError("Expected two grounded junction edges for the 20 mm fillets")
    outer = wp(outer).newObject(junction_edges).fillet(20.0).val()

    # Apply R5 to the remaining sharp outer edges. Edges belonging to the new
    # R20 transition are excluded so their specified radius is retained.
    outer_r5 = []
    for edge in outer.Edges():
        bb = edge.BoundingBox()
        c = edge.Center()
        near_r20_transition = (
            bb.xmin >= 79.999 and bb.xmax <= 100.001
            and (bb.ymax <= 230.001 or bb.ymin >= 289.999)
        )
        if is_line(edge) and not near_r20_transition:
            outer_r5.append(edge)

    print("OUTER R5 CANDIDATES:", len(outer_r5))
    if outer_r5:
        try:
            candidate = wp(outer).newObject(outer_r5).fillet(5.0).val()
            if candidate.isValid():
                outer = candidate
                print("Applied outer R5 set simultaneously")
        except Exception as exc:
            print("Combined outer R5 failed; applying stable edge groups:", exc)
            # Prefer long axis-aligned edges and free-end vertical edges. This
            # avoids over-constraining the small 5 mm lower level difference.
            groups = []
            current_edges = list(outer.Edges())
            groups.append([e for e in current_edges if is_line(e) and e.Length() > 20.0
                           and abs(e.BoundingBox().xlen) > 20.0])
            groups.append([e for e in current_edges if is_line(e) and is_vertical(e)
                           and abs(e.Center().x - 100.0) > 1.0e-3])
            for group in groups:
                if not group:
                    continue
                try:
                    trial = wp(outer).newObject(group).fillet(5.0).val()
                    if trial.isValid():
                        outer = trial
                except Exception as group_exc:
                    print("Skipped incompatible R5 group:", group_exc)

    # Restore the grounded blind longitudinal socket after replacing the outer
    # feature history. It opens at x=300 and terminates at x=100.
    bore_radius = 14.142135623730951
    bore = cq.Solid.makeCylinder(
        bore_radius, 200.0,
        cq.Vector(100.0, 270.0, -400.0),
        cq.Vector(1.0, 0.0, 0.0)
    )
    result = outer.cut(bore)

    # Radius the circular bore mouth and blind seating edge by R5 where OCC can
    # form the requested concave rounds.
    bore_edges = []
    for edge in result.Edges():
        bb = edge.BoundingBox()
        c = edge.Center()
        if (edge.geomType() == "CIRCLE"
                and (abs(c.x - 100.0) < 1.0e-3 or abs(c.x - 300.0) < 1.0e-3)
                and abs(c.y - 270.0) < 1.0e-2
                and abs(c.z + 400.0) < 1.0e-2):
            bore_edges.append(edge)
    print("BORE R5 EDGES:", len(bore_edges))
    if bore_edges:
        try:
            trial = wp(result).newObject(bore_edges).fillet(5.0).val()
            if trial.isValid():
                result = trial
        except Exception as exc:
            print("Bore R5 set could not be formed:", exc)

    # Restore the grounded rectangular side pocket (F003). It opens through
    # y=230 and terminates at y=280.
    pocket = cq.Solid.makeBox(
        168.336333 - 125.350920,
        50.0,
        -374.121747 - (-405.071245),
        cq.Vector(125.350920, 230.0, -405.071245)
    )
    result = result.cut(pocket)

    # Apply R5 to the pocket edges as the remaining edge family. Attempt the
    # complete set first, then the four longitudinal pocket edges if the bore
    # intersection makes the complete rolling-ball solution incompatible.
    pocket_edges = []
    for edge in result.Edges():
        bb = edge.BoundingBox()
        c = edge.Center()
        in_x = 125.34 <= c.x <= 168.35
        in_y = 229.99 <= c.y <= 280.01
        in_z = -405.08 <= c.z <= -374.11
        if is_line(edge) and in_x and in_y and in_z:
            pocket_edges.append(edge)

    print("POCKET R5 CANDIDATES:", len(pocket_edges))
    if pocket_edges:
        try:
            trial = wp(result).newObject(pocket_edges).fillet(5.0).val()
            if trial.isValid():
                result = trial
        except Exception as exc:
            print("Complete pocket R5 failed; trying edges parallel to Y:", exc)
            safe = []
            for edge in result.Edges():
                if not is_line(edge):
                    continue
                bb = edge.BoundingBox()
                c = edge.Center()
                if (125.34 <= c.x <= 168.35
                        and bb.ylen > 20.0
                        and bb.xlen < 1.0e-4
                        and bb.zlen < 1.0e-4
                        and -405.08 <= c.z <= -374.11):
                    safe.append(edge)
            if safe:
                try:
                    trial = wp(result).newObject(safe).fillet(5.0).val()
                    if trial.isValid():
                        result = trial
                except Exception as safe_exc:
                    print("Pocket fallback skipped:", safe_exc)

    result = result.clean()
    if not result.isValid():
        raise ValueError("Final reconstructed solid is invalid")

    bb = result.BoundingBox()
    print("FINAL VALID:", result.isValid())
    print("FINAL SOLIDS:", len(result.Solids()), "FACES:", len(result.Faces()), "EDGES:", len(result.Edges()))
    print("FINAL BBOX:", (bb.xmin, bb.ymin, bb.zmin), (bb.xmax, bb.ymax, bb.zmax))
    print("FINAL VOLUME:", result.Volume())
    return cq.Workplane("XY").newObject([result])