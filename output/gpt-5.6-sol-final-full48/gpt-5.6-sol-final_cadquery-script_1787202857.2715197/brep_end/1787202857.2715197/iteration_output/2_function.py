def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    root = model.val()
    solids = list(root.Solids())

    if not solids:
        raise ValueError("The imported STEP model contains no solids.")

    def find_target_edge(shape):
        candidates = []
        for edge in shape.Edges():
            if edge.geomType() != "LINE":
                continue
            bb = edge.BoundingBox()
            c = edge.Center()
            if edge.Length() > 300.0 and bb.ylen < 1.0e-5 and abs(c.y) < 1.0e-4:
                candidates.append(edge)
        if len(candidates) != 1:
            details = [
                (e.Length(), e.Center().x, e.Center().y, e.Center().z)
                for e in candidates
            ]
            raise ValueError(
                "Expected one sharp full-length blade edge, found %d: %s"
                % (len(candidates), details)
            )
        return candidates[0]

    original_blade = solids[0]

    # Topological cleanup can make imported STEP edges more suitable for the
    # OpenCascade fillet builder without changing their underlying geometry.
    try:
        blade = original_blade.clean()
        if blade is None or blade.isNull() or not blade.isValid():
            blade = original_blade
    except Exception:
        blade = original_blade

    target_edge = find_target_edge(blade)
    nominal_radius = 6.35
    edited_blade = None
    applied_radius = None

    # R=6.35 mm is apparently the limiting half-thickness radius. OpenCascade
    # can reject a fillet exactly at such a limit, so first try the nominal
    # value and then numerically indistinguishable undercuts.
    for radius in (6.35, 6.3499, 6.349, 6.34):
        try:
            candidate = blade.fillet(radius, [target_edge])
            if (
                candidate is not None
                and not candidate.isNull()
                and candidate.isValid()
                and len(candidate.Solids()) == 1
                and candidate.Volume() < blade.Volume()
            ):
                edited_blade = candidate
                applied_radius = radius
                break
        except Exception as exc:
            print("Fillet attempt R=%.4f mm failed: %s" % (radius, exc))

    # Fallback for a limiting-radius condition: construct the exact cylindrical
    # edge round as a local swept cut. This creates the same constant-radius
    # surface while avoiding the fillet builder's zero-width terminal face.
    if edited_blade is None:
        edge = target_edge
        adjacent = []
        for face in blade.Faces():
            if face.geomType() != "PLANE":
                continue
            for face_edge in face.Edges():
                try:
                    same = face_edge.wrapped.IsSame(edge.wrapped)
                except Exception:
                    same = False
                if same:
                    adjacent.append(face)
                    break

        if len(adjacent) != 2:
            raise RuntimeError(
                "Cannot construct the exact-radius fallback: target edge has "
                "%d adjacent planar faces instead of two." % len(adjacent)
            )

        vertices = edge.Vertices()
        if len(vertices) != 2:
            raise RuntimeError("The target longitudinal edge has no two endpoints.")

        p0 = vertices[0].Center()
        p1 = vertices[1].Center()
        axis_vec = p1.sub(p0)
        edge_length = axis_vec.Length
        d = axis_vec.normalized()
        midpoint = edge.Center()
        to_interior = blade.Center().sub(midpoint)

        inward = []
        for face in adjacent:
            n = face.normalAt(midpoint).normalized()
            # Remove any tiny numerical component parallel to the edge.
            n = n.sub(d.multiply(n.dot(d))).normalized()
            if to_interior.dot(n) < 0.0:
                n = n.multiply(-1.0)
            inward.append(n)

        u = inward[0]
        v = inward[1]
        if abs(u.dot(v)) > 1.0e-3:
            raise RuntimeError(
                "Exact-radius fallback requires perpendicular blade faces; dot=%g"
                % u.dot(v)
            )

        # Re-orthogonalize to suppress imported STEP tolerances.
        v = v.sub(u.multiply(v.dot(u))).normalized()
        r = nominal_radius
        extension = 1.0
        start = p0.sub(d.multiply(extension))

        q0 = start
        q1 = start.add(u.multiply(r))
        q2 = start.add(u.multiply(r)).add(v.multiply(r))
        q3 = start.add(v.multiply(r))

        square_wire = cq.Wire.makePolygon(
            [q0.toTuple(), q1.toTuple(), q2.toTuple(), q3.toTuple()],
            close=True,
        )
        square_prism = cq.Solid.extrudeLinear(
            square_wire,
            [],
            d.multiply(edge_length + 2.0 * extension),
        )
        cylinder_origin = start.add(u.multiply(r)).add(v.multiply(r))
        tangent_cylinder = cq.Solid.makeCylinder(
            r,
            edge_length + 2.0 * extension,
            cylinder_origin,
            d,
        )
        corner_cutter = square_prism.cut(tangent_cylinder)
        candidate = blade.cut(corner_cutter)

        if candidate is None or candidate.isNull() or not candidate.isValid():
            raise RuntimeError("The exact 6.35 mm cylindrical fallback cut failed.")
        if len(candidate.Solids()) != 1:
            raise RuntimeError("The fallback cut split the blade unexpectedly.")
        if candidate.Volume() >= blade.Volume():
            raise RuntimeError("The fallback cut did not remove the sharp corner.")

        edited_blade = candidate
        applied_radius = nominal_radius
        print("Used exact cylindrical fallback for R=6.35 mm.")

    output_solids = [edited_blade] + solids[1:]
    result = cq.Compound.makeCompound(output_solids)

    if result.isNull() or not result.isValid():
        raise RuntimeError("The final preserved assembly is invalid.")

    c = target_edge.Center()
    print(
        "Rounded blade edge: length=%.6f, center=(%.6f, %.6f, %.6f), R=%.4f mm"
        % (target_edge.Length(), c.x, c.y, c.z, applied_radius)
    )
    print("Original blade volume:", round(original_blade.Volume(), 6))
    print("Edited blade volume:", round(edited_blade.Volume(), 6))
    print("Preserved additional solids:", len(solids) - 1)

    return cq.Workplane("XY").newObject([result])