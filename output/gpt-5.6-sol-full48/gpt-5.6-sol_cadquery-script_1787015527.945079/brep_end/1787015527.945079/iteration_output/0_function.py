def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    base = imported.val()

    bbox = base.BoundingBox()
    y_min = bbox.ymin
    y_max = bbox.ymax
    thickness = y_max - y_min

    # Recover the original bore center and radius from its circular boundary edges.
    bore_candidates = []
    for edge in base.Edges():
        try:
            if edge.geomType() == "CIRCLE":
                radius = edge.radius()
                center = edge.Center()
                print(
                    "Circular edge: radius=%.6f center=(%.6f, %.6f, %.6f)"
                    % (radius, center.x, center.y, center.z)
                )
                if abs(radius - 10.0) < 0.25:
                    bore_candidates.append((center, radius))
        except Exception:
            pass

    if bore_candidates:
        cx = sum(item[0].x for item in bore_candidates) / len(bore_candidates)
        cz = sum(item[0].z for item in bore_candidates) / len(bore_candidates)
        bore_radius = sum(item[1] for item in bore_candidates) / len(bore_candidates)
    else:
        # Nominal Sketch4 geometry from the supplied feature plan.
        cx = 0.0
        cz = 10.0
        bore_radius = 10.0

    print("Input valid:", base.isValid())
    print("Input faces:", len(base.Faces()))
    print("Thickness range: y=%.6f to %.6f" % (y_min, y_max))
    print(
        "Selected bore: center=(%.6f, %.6f), radius=%.6f"
        % (cx, cz, bore_radius)
    )

    # Restore the material removed by the original cylindrical through-hole.
    plug = cq.Solid.makeCylinder(
        bore_radius,
        thickness,
        cq.Vector(cx, y_min, cz),
        cq.Vector(0, 1, 0),
    )
    restored = base.fuse(plug)

    # Sketch4 lies normal to the thickness direction. Create a regular hexagon
    # whose six vertices lie on the recovered radius-10 construction circle.
    clearance = 1.0
    sketch_plane = cq.Plane(
        origin=(cx, y_min - clearance, cz),
        xDir=(1, 0, 0),
        normal=(0, 1, 0),
    )
    hexagonal_cutter = (
        cq.Workplane(sketch_plane)
        .polygon(6, 2.0 * bore_radius, circumscribed=False)
        .extrude(thickness + 2.0 * clearance)
        .val()
    )

    result = restored.cut(hexagonal_cutter)
    print("Result valid:", result.isValid())
    print("Result solids:", len(result.Solids()))
    print("Result faces:", len(result.Faces()))
    print(
        "Replaced cylindrical bore with through-all regular hexagon: "
        "across corners=%.6f, across flats=%.6f"
        % (2.0 * bore_radius, (3.0 ** 0.5) * bore_radius)
    )

    return cq.Workplane("XY").newObject([result])