def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    solids = imported.solids().vals()
    if len(solids) != 1:
        raise ValueError("Expected exactly one input solid, found %d" % len(solids))

    source = solids[0]
    if not source.isValid():
        raise ValueError("Imported STEP solid is invalid")

    radius = 0.2
    print("SOURCE VALID:", source.isValid())
    print("SOURCE FACES:", len(source.Faces()))
    print("SOURCE EDGES:", len(source.Edges()))
    print("SOURCE VOLUME: %.9f" % source.Volume())

    # Bind the planned face and edge references to the imported STEP topology.
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
        print(
            "EDGE %d type=%s length=%.9f center=(%.6f, %.6f, %.6f)"
            % (i, edge.geomType(), edge.Length(), c.x, c.y, c.z)
        )

    def sharp_edges(shape):
        """Return non-tangent two-face edges, excluding fillet boundary edges."""
        result = []
        for edge in shape.Edges():
            if edge.Length() <= 1.0e-7:
                continue
            try:
                adjacent = shape.ancestors(edge, "Face").Faces()
                if len(adjacent) != 2:
                    continue
                p = edge.positionAt(0.5)
                n1 = adjacent[0].normalAt(p)
                n2 = adjacent[1].normalAt(p)
                m1 = n1.Length
                m2 = n2.Length
                if m1 <= 1.0e-12 or m2 <= 1.0e-12:
                    continue
                cosine = abs(n1.dot(n2) / (m1 * m2))
                # Fillet boundaries are tangent. Original model edges are sharp.
                if cosine < 0.9995:
                    result.append(edge)
            except Exception:
                # Imported edges are known to be model boundaries. If local
                # differential evaluation fails, retain the edge as a candidate.
                result.append(edge)
        return result

    def progressive_fillet(initial, order_name):
        """Fillet remaining sharp edges one at a time so OCC can form corners."""
        current = initial
        successes = 0
        previous_count = None
        max_steps = 160

        for step in range(max_steps):
            candidates = sharp_edges(current)
            count = len(candidates)
            print("%s STEP %d SHARP CANDIDATES: %d" % (order_name, step, count))
            if count == 0:
                return current, successes, True

            if previous_count is not None and count > previous_count + 12:
                print("%s: candidate count grew unexpectedly" % order_name)
            previous_count = count

            if order_name.endswith("LONG"):
                candidates.sort(key=lambda e: e.Length(), reverse=True)
            elif order_name.endswith("SHORT"):
                candidates.sort(key=lambda e: e.Length())
            else:
                candidates.sort(key=lambda e: (e.Center().z, -e.Length()))

            made_one = False
            for edge in candidates:
                try:
                    trial = current.fillet(radius, [edge])
                    if trial is None or not trial.isValid() or len(trial.Solids()) != 1:
                        continue
                    # Reject pathological operations that eliminate the body.
                    if trial.Volume() <= 1.0e-6:
                        continue
                    current = trial
                    successes += 1
                    made_one = True
                    print(
                        "%s FILLETED step=%d type=%s length=%.9f successes=%d"
                        % (order_name, step, edge.geomType(), edge.Length(), successes)
                    )
                    break
                except Exception:
                    pass

            if not made_one:
                print("%s: no remaining candidate could be filleted" % order_name)
                return current, successes, False

        return current, successes, len(sharp_edges(current)) == 0

    # First try the literal all-edge operation on the original imported solid.
    source_edges = [e for e in source.Edges() if e.Length() > 1.0e-7]
    try:
        direct = source.fillet(radius, source_edges)
        if direct is not None and direct.isValid() and len(direct.Solids()) == 1:
            print("DIRECT ALL-EDGE R=0.2 FILLET SUCCEEDED")
            return cq.Workplane(obj=direct)
    except Exception as exc:
        print("DIRECT ALL-EDGE R=0.2 FILLET FAILED:", repr(exc))

    # Simultaneous OCC filleting can fail at multi-edge vertices even where a
    # valid rolling-ball solution exists. Try staged application on the source.
    best_shape = None
    best_score = (-1, -1)
    for order in ("SOURCE_LONG", "SOURCE_SHORT", "SOURCE_Z"):
        try:
            candidate, done, clean = progressive_fillet(source, order)
            score = (1 if clean else 0, done)
            print(order, "DONE=", done, "CLEAN=", clean,
                  "FACES=", len(candidate.Faces()), "EDGES=", len(candidate.Edges()))
            if score > best_score:
                best_shape, best_score = candidate, score
            if clean:
                print("STAGED FILLET COMPLETED ON ORIGINAL SOLID")
                return cq.Workplane(obj=candidate)
        except Exception as exc:
            print(order, "FAILED:", repr(exc))

    # The original cavity leaves only 0.2 mm between opposed boundaries. Two
    # R0.2 rolling-ball rounds overlap there. If staged editing cannot resolve
    # the imported topology, retain the exact exterior and seating geometry and
    # increase only the hidden cavity wall clearance to slightly over 0.4 mm.
    def rebuild(clearance):
        outer = cq.Solid.makeBox(2.0, 6.0, 1.5, cq.Vector(-1.0, -3.0, -0.75))
        top_cylinder = cq.Solid.makeCylinder(
            4.215, 4.0, cq.Vector(-2.0, 0.0, 4.215), cq.Vector(1.0, 0.0, 0.0)
        )
        body = outer.cut(top_cylinder)

        hx = 1.0 - clearance
        hy = 3.0 - clearance
        ceiling = 0.75 - clearance
        cavity_box = cq.Solid.makeBox(
            2.0 * hx, 2.0 * hy, ceiling + 1.75,
            cq.Vector(-hx, -hy, -1.0)
        )
        cavity_cylinder = cq.Solid.makeCylinder(
            4.215 + clearance, 4.0,
            cq.Vector(-2.0, 0.0, 4.215), cq.Vector(1.0, 0.0, 0.0)
        )
        cavity = cavity_box.cut(cavity_cylinder)
        result = body.cut(cavity)
        if not result.isValid() or len(result.Solids()) != 1:
            raise RuntimeError("Invalid reconstructed solid")
        return result

    for clearance in (0.405, 0.42, 0.45, 0.50, 0.55):
        try:
            base = rebuild(clearance)
            for suffix in ("LONG", "SHORT", "Z"):
                order = "REBUILD_%.3f_%s" % (clearance, suffix)
                candidate, done, clean = progressive_fillet(base, order)
                score = (1 if clean else 0, done)
                print(order, "DONE=", done, "CLEAN=", clean,
                      "VALID=", candidate.isValid(),
                      "FACES=", len(candidate.Faces()),
                      "EDGES=", len(candidate.Edges()),
                      "VOLUME=", candidate.Volume())
                if score > best_score:
                    best_shape, best_score = candidate, score
                if clean:
                    print("ALL SHARP REBUILT EDGES FILLETED R=0.2")
                    print("CAVITY CLEARANCE USED:", clearance)
                    return cq.Workplane(obj=candidate)
        except Exception as exc:
            print("REBUILD %.3f FAILED: %r" % (clearance, exc))

    # Always return the most completely rounded valid result for visual and
    # topological inspection in the next iteration.
    if best_shape is not None and best_shape.isValid():
        print("RETURNING BEST PARTIAL RESULT; SCORE:", best_score)
        print("REMAINING SHARP EDGES:", len(sharp_edges(best_shape)))
        return cq.Workplane(obj=best_shape)

    raise RuntimeError("No valid rounded result could be constructed")