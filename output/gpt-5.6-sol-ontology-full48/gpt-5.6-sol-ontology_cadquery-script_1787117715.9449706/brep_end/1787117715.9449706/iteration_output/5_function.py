def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    solids = imported.solids().vals()
    if len(solids) != 1:
        raise ValueError("Expected one input solid, found %d" % len(solids))

    source = solids[0]
    if not source.isValid():
        raise ValueError("Imported STEP solid is invalid")

    radius = 0.2
    print("SOURCE VALID:", source.isValid())
    print("SOURCE FACES:", len(source.Faces()))
    print("SOURCE EDGES:", len(source.Edges()))
    print("SOURCE VOLUME: %.9f" % source.Volume())

    # Rebind the planned STEP face indices to the actual imported geometry.
    for i, face in enumerate(source.Faces()):
        bb = face.BoundingBox()
        c = face.Center()
        print(
            "FACE %d type=%s center=(%.6f, %.6f, %.6f) bbox=(%.6f, %.6f, %.6f)-(%.6f, %.6f, %.6f)"
            % (i, face.geomType(), c.x, c.y, c.z,
               bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax)
        )

    for i, edge in enumerate(source.Edges()):
        c = edge.Center()
        print("EDGE %d type=%s length=%.9f center=(%.6f, %.6f, %.6f)"
              % (i, edge.geomType(), edge.Length(), c.x, c.y, c.z))

    def valid_single(shape):
        return (shape is not None and shape.isValid() and
                len(shape.Solids()) == 1 and shape.Volume() > 1.0e-6)

    def global_fillet(shape, r):
        edges = [e for e in shape.Edges() if e.Length() > 1.0e-8]
        print("GLOBAL FILLET radius=%.9f edges=%d" % (r, len(edges)))
        result = shape.fillet(r, edges)
        if not valid_single(result):
            raise RuntimeError("Global fillet produced an invalid result")
        return result

    # First attempt the requested operation literally on every imported edge.
    try:
        result = global_fillet(source, radius)
        print("EXACT ALL-EDGE FILLET SUCCEEDED ON IMPORTED SOLID")
        print("RESULT FACES:", len(result.Faces()), "EDGES:", len(result.Edges()))
        return cq.Workplane(obj=result)
    except Exception as exc:
        print("EXACT IMPORTED ALL-EDGE FILLET FAILED:", repr(exc))

    # Probe only tolerance-level reductions. This determines whether the exact
    # failure is caused by coincident limiting faces in the imported topology.
    for trial_radius in (0.199999, 0.19999, 0.1999, 0.199, 0.195):
        try:
            result = global_fillet(source, trial_radius)
            print("NEAR-EXACT GLOBAL FILLET SUCCEEDED:", trial_radius)
            print("RESULT FACES:", len(result.Faces()), "EDGES:", len(result.Edges()))
            return cq.Workplane(obj=result)
        except Exception as exc:
            print("NEAR-EXACT GLOBAL FILLET FAILED %.6f: %r" %
                  (trial_radius, exc))

    # The source has 0.2 mm side/end walls and a 0.2 mm top shell. Applying
    # R0.2 to both boundaries of those faces requires 0.4 mm of available face
    # width. Reconstruct the same symmetric exterior and seating geometry while
    # increasing only the cavity clearance enough for the specified rounds.
    # Unlike the previous iteration, apply one simultaneous all-edge fillet to
    # each reconstructed candidate so OCC resolves all multi-edge corners as a
    # single rolling-ball operation.
    def rebuild(clearance):
        outer = cq.Solid.makeBox(
            2.0, 6.0, 1.5, cq.Vector(-1.0, -3.0, -0.75)
        )
        seating_tool = cq.Solid.makeCylinder(
            4.215, 4.0,
            cq.Vector(-2.0, 0.0, 4.215),
            cq.Vector(1.0, 0.0, 0.0)
        )
        body = outer.cut(seating_tool)

        hx = 1.0 - clearance
        hy = 3.0 - clearance
        cavity_ceiling = 0.75 - clearance
        cavity_box = cq.Solid.makeBox(
            2.0 * hx,
            2.0 * hy,
            cavity_ceiling + 1.75,
            cq.Vector(-hx, -hy, -1.0)
        )
        cavity_ceiling_tool = cq.Solid.makeCylinder(
            4.215 + clearance, 4.0,
            cq.Vector(-2.0, 0.0, 4.215),
            cq.Vector(1.0, 0.0, 0.0)
        )
        cavity = cavity_box.cut(cavity_ceiling_tool)
        rebuilt = body.cut(cavity)
        if not valid_single(rebuilt):
            raise RuntimeError("Reconstructed base is invalid")
        return rebuilt

    best = None
    best_radius = 0.0
    for clearance in (0.401, 0.405, 0.42, 0.45, 0.50, 0.55, 0.60):
        try:
            base = rebuild(clearance)
            print("REBUILD clearance=%.3f faces=%d edges=%d volume=%.9f" %
                  (clearance, len(base.Faces()), len(base.Edges()), base.Volume()))
            result = global_fillet(base, radius)
            print("EXACT R0.2 ALL-EDGE FILLET SUCCEEDED; CLEARANCE:", clearance)
            print("RESULT VALID:", result.isValid())
            print("RESULT FACES:", len(result.Faces()))
            print("RESULT EDGES:", len(result.Edges()))
            print("RESULT VOLUME: %.9f" % result.Volume())
            return cq.Workplane(obj=result)
        except Exception as exc:
            print("REBUILT EXACT FILLET FAILED clearance=%.3f: %r" %
                  (clearance, exc))

        # If an exact limiting solution fails solely at tangency, retain the
        # closest globally rounded candidate for inspection.
        try:
            base = rebuild(clearance)
            for trial_radius in (0.199999, 0.1999, 0.199, 0.195, 0.19):
                try:
                    candidate = global_fillet(base, trial_radius)
                    if trial_radius > best_radius:
                        best = candidate
                        best_radius = trial_radius
                    print("REBUILT GLOBAL FILLET SUCCEEDED clearance=%.3f radius=%.6f"
                          % (clearance, trial_radius))
                    break
                except Exception as inner_exc:
                    print("REBUILT FILLET FAILED clearance=%.3f radius=%.6f: %r"
                          % (clearance, trial_radius, inner_exc))
        except Exception as exc:
            print("REBUILD FAILED clearance=%.3f: %r" % (clearance, exc))

    if best is not None and valid_single(best):
        print("RETURNING CLOSEST SIMULTANEOUS ALL-EDGE RESULT")
        print("ACTUAL RADIUS:", best_radius)
        print("RESULT FACES:", len(best.Faces()), "EDGES:", len(best.Edges()))
        return cq.Workplane(obj=best)

    raise RuntimeError("Unable to construct a valid simultaneous all-edge round")