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
            return cq.Shape.cast(unifier.Shape()).clean()
        except Exception as exc:
            print("Same-domain unification warning:", exc)
            try:
                return shape.clean()
            except Exception:
                return shape

    input_file = os.path.expanduser(args["input_file"])
    base = cq.importers.importStep(input_file).val()
    bbox = base.BoundingBox()
    y_min, y_max = bbox.ymin, bbox.ymax
    thickness = y_max - y_min

    bore_candidates = []
    for edge in base.Edges():
        try:
            if edge.geomType() == "CIRCLE" and abs(edge.radius() - 10.0) < 0.25:
                bore_candidates.append((edge.Center(), edge.radius()))
        except Exception:
            pass

    if bore_candidates:
        cx = sum(c.x for c, r in bore_candidates) / len(bore_candidates)
        cz = sum(c.z for c, r in bore_candidates) / len(bore_candidates)
        bore_radius = sum(r for c, r in bore_candidates) / len(bore_candidates)
    else:
        cx, cz, bore_radius = 0.0, 10.0, 10.0

    print("Input valid:", base.isValid())
    print("Input faces:", len(base.Faces()))
    print("Original bounds: y=%.6f to %.6f" % (y_min, y_max))
    print("Recovered Sketch4 circle: center=(%.6f, %.6f), radius=%.6f" % (cx, cz, bore_radius))

    plug = cq.Solid.makeCylinder(
        bore_radius + 0.30,
        thickness,
        cq.Vector(cx, y_min, cz),
        cq.Vector(0, 1, 0),
    )
    restored = unify_same_domain(base.fuse(plug))

    cut_margin = 1.0
    sketch_plane = cq.Plane(
        origin=(cx, y_min - cut_margin, cz),
        xDir=(1, 0, 0),
        normal=(0, 1, 0),
    )
    cutter = (
        cq.Workplane(sketch_plane)
        .polygon(6, 2.0 * bore_radius, circumscribed=False)
        .extrude(thickness + 2.0 * cut_margin)
        .val()
    )

    result = unify_same_domain(restored.cut(cutter))

    residual_bore_faces = 0
    planar_socket_faces = 0
    for face in result.Faces():
        try:
            if face.geomType() == "CYLINDER":
                radius = BRepAdaptor_Surface(face.wrapped).Cylinder().Radius()
                if abs(radius - bore_radius) < 0.05:
                    residual_bore_faces += 1
            elif face.geomType() == "PLANE":
                bb = face.BoundingBox()
                center = face.Center()
                near_eye = abs(center.x - cx) <= bore_radius + 0.5 and abs(center.z - cz) <= bore_radius + 0.5
                if near_eye and bb.ylen >= thickness - 0.05:
                    planar_socket_faces += 1
        except Exception:
            pass

    result_bbox = result.BoundingBox()
    print("Result valid:", result.isValid())
    print("Result solids:", len(result.Solids()))
    print("Result faces:", len(result.Faces()))
    print("Result bounds: y=%.6f to %.6f" % (result_bbox.ymin, result_bbox.ymax))
    print("Residual radius-10 cylindrical bore faces:", residual_bore_faces)
    print("Detected through-thickness planar socket faces:", planar_socket_faces)
    print("Hexagonal Through All cut: across corners=%.6f, across flats=%.6f" % (2.0 * bore_radius, math.sqrt(3.0) * bore_radius))

    return cq.Workplane("XY").newObject([result])