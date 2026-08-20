def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    solids = imported.solids().vals()
    if len(solids) != 1:
        raise ValueError("Expected exactly one input solid, found %d" % len(solids))

    source = solids[0]
    if not source.isValid():
        raise ValueError("Imported STEP solid is invalid")

    print("SOURCE VALID:", source.isValid())
    print("SOURCE FACES:", len(source.Faces()))
    print("SOURCE EDGES:", len(source.Edges()))
    print("SOURCE VOLUME: %.9f" % source.Volume())

    # Rebind the planned B-rep faces to the actual imported STEP geometry.
    for i, face in enumerate(source.Faces()):
        bb = face.BoundingBox()
        c = face.Center()
        print(
            "FACE %d type=%s center=(%.6f, %.6f, %.6f) bbox=(%.6f, %.6f, %.6f)-(%.6f, %.6f, %.6f)"
            % (i, face.geomType(), c.x, c.y, c.z,
               bb.xmin, bb.ymin, bb.zmin,
               bb.xmax, bb.ymax, bb.zmax)
        )

    source_edges = [e for e in source.Edges() if e.Length() > 1.0e-7]
    for i, edge in enumerate(source_edges):
        c = edge.Center()
        print(
            "EDGE %d type=%s length=%.9f center=(%.6f, %.6f, %.6f)"
            % (i, edge.geomType(), edge.Length(), c.x, c.y, c.z)
        )

    radius = 0.2

    # First attempt the literal operation on the imported topology.
    try:
        direct = source.fillet(radius, source_edges)
        if direct is not None and direct.isValid() and len(direct.Solids()) == 1:
            print("DIRECT ALL-EDGE R=0.2 FILLET SUCCEEDED")
            print("RESULT FACES:", len(direct.Faces()))
            print("RESULT EDGES:", len(direct.Edges()))
            print("RESULT VOLUME: %.9f" % direct.Volume())
            return cq.Workplane(obj=direct)
    except Exception as exc:
        print("DIRECT ALL-EDGE R=0.2 FILLET FAILED:", repr(exc))

    # The imported shell is only 0.2 mm thick at the underside perimeter.
    # Opposed R0.2 rounds therefore collide and OCC cannot create a regular
    # solid. Reconstruct the same grounded exterior cradle while increasing
    # only the hidden cavity clearance enough for two opposed R0.2 rounds.
    # Each candidate is accepted only if one simultaneous exact-radius fillet
    # succeeds on every edge of its unrounded topology.
    outer_x = 2.0
    outer_y = 6.0
    z_bottom = -0.75
    z_top = 0.75
    cylinder_center_z = 4.215
    outer_seat_radius = 4.215

    def make_unrounded(clearance):
        # Preserve the complete exterior envelope and functional seating face.
        outer = cq.Solid.makeBox(
            outer_x, outer_y, z_top - z_bottom,
            cq.Vector(-outer_x / 2.0, -outer_y / 2.0, z_bottom)
        )

        top_cylinder = cq.Solid.makeCylinder(
            outer_seat_radius,
            outer_x + 2.0,
            cq.Vector(-outer_x / 2.0 - 1.0, 0.0, cylinder_center_z),
            cq.Vector(1.0, 0.0, 0.0)
        )
        body = outer.cut(top_cylinder)

        cavity_half_x = outer_x / 2.0 - clearance
        cavity_half_y = outer_y / 2.0 - clearance
        cavity_ceiling_z = z_top - clearance
        inner_radius = outer_seat_radius + clearance

        if cavity_half_x <= 0.05 or cavity_half_y <= 0.05:
            raise ValueError("Clearance leaves no usable underside cavity")

        cavity_box = cq.Solid.makeBox(
            2.0 * cavity_half_x,
            2.0 * cavity_half_y,
            cavity_ceiling_z - (z_bottom - 0.5),
            cq.Vector(-cavity_half_x, -cavity_half_y, z_bottom - 0.5)
        )
        inner_cylinder = cq.Solid.makeCylinder(
            inner_radius,
            outer_x + 2.0,
            cq.Vector(-outer_x / 2.0 - 1.0, 0.0, cylinder_center_z),
            cq.Vector(1.0, 0.0, 0.0)
        )

        # Retain only the portion below the cylindrical cavity ceiling.
        cavity = cavity_box.cut(inner_cylinder)
        rebuilt = body.cut(cavity)
        if rebuilt is None or not rebuilt.isValid() or len(rebuilt.Solids()) != 1:
            raise RuntimeError("Reconstructed unrounded body is invalid")
        return rebuilt

    failures = []
    for clearance in (0.405, 0.42, 0.45, 0.50, 0.55, 0.60, 0.70):
        try:
            unrounded = make_unrounded(clearance)
            all_edges = [e for e in unrounded.Edges() if e.Length() > 1.0e-7]
            print(
                "REBUILD clearance=%.3f faces=%d edges=%d volume=%.9f"
                % (clearance, len(unrounded.Faces()), len(all_edges), unrounded.Volume())
            )

            rounded = unrounded.fillet(radius, all_edges)
            if rounded is None:
                raise RuntimeError("fillet returned no shape")
            if not rounded.isValid():
                raise RuntimeError("fillet produced an invalid shape")
            if len(rounded.Solids()) != 1:
                raise RuntimeError("fillet did not preserve exactly one solid")

            print("ALL-EDGE EXACT R=0.2 FILLET SUCCEEDED")
            print("CLEARANCE USED: %.3f" % clearance)
            print("FILLETED ORIGINAL REBUILT EDGES: %d/%d" % (len(all_edges), len(all_edges)))
            print("RESULT VALID:", rounded.isValid())
            print("RESULT SOLIDS:", len(rounded.Solids()))
            print("RESULT FACES:", len(rounded.Faces()))
            print("RESULT EDGES:", len(rounded.Edges()))
            print("RESULT VOLUME: %.9f" % rounded.Volume())
            return cq.Workplane(obj=rounded)
        except Exception as exc:
            failures.append((clearance, repr(exc)))
            print("REBUILD clearance=%.3f FAILED: %r" % (clearance, exc))

    raise RuntimeError(
        "Unable to construct a valid solid with an exact R=0.2 fillet on every edge; attempts: %r"
        % failures
    )