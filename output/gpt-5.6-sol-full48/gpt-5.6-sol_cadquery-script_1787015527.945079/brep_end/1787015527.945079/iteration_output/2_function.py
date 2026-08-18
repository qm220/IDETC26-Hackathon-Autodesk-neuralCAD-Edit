def my_cad_function(args):
    import os
    import math
    import cadquery as cq
    from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain

    def unify_same_domain(shape):
        try:
            unifier = ShapeUpgrade_UnifySameDomain(shape.wrapped, True, True, True)
            unifier.Build()
            return cq.Shape.cast(unifier.Shape())
        except Exception as exc:
            print("Same-domain unification warning:", exc)
            try:
                return shape.clean()
            except Exception:
                return shape

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    base = imported.val()

    bbox = base.BoundingBox()
    y_min = bbox.ymin
    y_max = bbox.ymax
    thickness = y_max - y_min

    # Recover the original Sketch4 circular bore from its radius-10 edges.
    bore_candidates = []
    for edge in base.Edges():
        try:
            if edge.geomType() == "CIRCLE":
                radius = edge.radius()
                center = edge.Center()
                if abs(radius - 10.0) < 0.25:
                    bore_candidates.append((center, radius))
        except Exception:
            pass

    if bore_candidates:
        cx = sum(item[0].x for item in bore_candidates) / len(bore_candidates)
        cz = sum(item[0].z for item in bore_candidates) / len(bore_candidates)
        bore_radius = sum(item[1] for item in bore_candidates) / len(bore_candidates)
    else:
        cx = 0.0
        cz = 10.0
        bore_radius = 10.0

    print("Input valid:", base.isValid())
    print("Input faces:", len(base.Faces()))
    print("Thickness range: y=%.6f to %.6f" % (y_min, y_max))
    print(
        "Recovered Sketch4 circle: center=(%.6f, %.6f), radius=%.6f"
        % (cx, cz, bore_radius)
    )

    # Restore the exact original circular bore volume. Using the exact bore
    # radius avoids creating the visible oversized circular partition left by
    # the previous radial-overlap plug. Axial extension makes the fuse robust.
    axial_margin = 0.5
    plug = cq.Solid.makeCylinder(
        bore_radius,
        thickness + 2.0 * axial_margin,
        cq.Vector(cx, y_min - axial_margin, cz),
        cq.Vector(0, 1, 0),
    )

    restored = base.fuse(plug)
    restored = unify_same_domain(restored)

    # Create a regular six-sided profile inscribed in the recovered circle.
    # Its vertex-to-vertex diameter equals the original 20 mm bore diameter.
    cut_margin = 1.0
    sketch_plane = cq.Plane(
        origin=(cx, y_min - cut_margin, cz),
        xDir=(1, 0, 0),
        normal=(0, 1, 0),
    )
    hexagonal_cutter = (
        cq.Workplane(sketch_plane)
        .polygon(6, 2.0 * bore_radius, circumscribed=False)
        .extrude(thickness + 2.0 * cut_margin)
        .val()
    )

    # Through-all replacement cut across the complete wrench thickness.
    result = restored.cut(hexagonal_cutter)
    result = unify_same_domain(result)

    # Confirm that the old radius-10 cylindrical bore wall is absent.
    old_bore_faces = 0
    planar_socket_faces = 0
    for face in result.Faces():
        try:
            if face.geomType() == "CYLINDER":
                radii = []
                for edge in face.Edges():
                    if edge.geomType() == "CIRCLE":
                        radii.append(edge.radius())
                if any(abs(r - bore_radius) < 0.05 for r in radii):
                    old_bore_faces += 1
            elif face.geomType() == "PLANE":
                center = face.Center()
                if abs(center.x - cx) < bore_radius + 0.5 and abs(center.z - cz) < bore_radius + 0.5:
                    bb = face.BoundingBox()
                    if bb.ylen >= thickness - 0.05:
                        planar_socket_faces += 1
        except Exception:
            pass

    print("Result valid:", result.isValid())
    print("Result solids:", len(result.Solids()))
    print("Result faces:", len(result.Faces()))
    print("Residual radius-10 cylindrical bore faces:", old_bore_faces)
    print("Detected through-thickness planar socket faces:", planar_socket_faces)
    print(
        "Hexagonal Through All cut: across corners=%.6f, across flats=%.6f"
        % (2.0 * bore_radius, math.sqrt(3.0) * bore_radius)
    )

    return cq.Workplane("XY").newObject([result])