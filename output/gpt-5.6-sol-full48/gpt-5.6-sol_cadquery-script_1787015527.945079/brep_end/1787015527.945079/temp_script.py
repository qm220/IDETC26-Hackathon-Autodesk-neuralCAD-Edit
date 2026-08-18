def my_cad_function(args):
    import os
    import math
    import cadquery as cq
    from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
    from OCP.BRepAdaptor import BRepAdaptor_Surface

    def unify_same_domain(shape):
        try:
            unifier = ShapeUpgrade_UnifySameDomain(shape.wrapped, True, True, True)
            unifier.Build()
            unified = cq.Shape.cast(unifier.Shape())
            return unified.clean()
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

    # Recover the original Sketch4 circle from radius-10 circular edges.
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
    print("Original bounds: y=%.6f to %.6f" % (y_min, y_max))
    print(
        "Recovered Sketch4 circle: center=(%.6f, %.6f), radius=%.6f"
        % (cx, cz, bore_radius)
    )

    # Restore the original circular opening before making the smaller inscribed
    # hexagonal cut. The plug is slightly oversized radially so it overlaps the
    # eye rim and produces a true union rather than merely touching the old
    # cylindrical wall. Its axial extent exactly matches the original body,
    # preventing raised bosses on either wrench face.
    radial_overlap = 0.30
    plug = cq.Solid.makeCylinder(
        bore_radius + radial_overlap,
        thickness,
        cq.Vector(cx, y_min, cz),
        cq.Vector(0, 1, 0),
    )

    restored = base.fuse(plug)
    restored = unify_same_domain(restored)

    # Create a regular hexagon inscribed in the recovered radius-10 circle.
    # CadQuery's polygon diameter is the across-corners diameter.
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

    # Replace the former circular bore with a through-all hexagonal socket.
    result = restored.cut(hexagonal_cutter)
    result = unify_same_domain(result)

    residual_bore_faces = 0
    planar_socket_faces = 0
    for face in result.Faces():
        try:
            if face.geomType() == "CYLINDER":
                adaptor = BRepAdaptor_Surface(face.wrapped)
                radius = adaptor.Cylinder().Radius()
                if abs(radius - bore_radius) < 0.05:
                    residual_bore_faces += 1
            elif face.geomType() == "PLANE":
                bb = face.BoundingBox()
                center = face.Center()
                near_eye = (
                    abs(center.x - cx) <= bore_radius + 0.5
                    and abs(center.z - cz) <= bore_radius + 0.5
                )
                if near_eye and bb.ylen >= thickness - 0.05:
                    planar_socket_faces += 1
        except Exception:
            pass

    result_bbox = result.BoundingBox()
    print("Result valid:", result.isValid())
    print("Result solids:", len(result.Solids()))
    print("Result faces:", len(result.Faces()))
    print(
        "Result bounds: y=%.6f to %.6f"
        % (result_bbox.ymin, result_bbox.ymax)
    )
    print("Residual radius-10 cylindrical bore faces:", residual_bore_faces)
    print("Detected through-thickness planar socket faces:", planar_socket_faces)
    print(
        "Hexagonal Through All cut: across corners=%.6f, across flats=%.6f"
        % (2.0 * bore_radius, math.sqrt(3.0) * bore_radius)
    )

    return cq.Workplane("XY").newObject([result])