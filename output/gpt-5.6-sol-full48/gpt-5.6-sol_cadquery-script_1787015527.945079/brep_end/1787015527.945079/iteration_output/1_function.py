def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    base = imported.val()

    bbox = base.BoundingBox()
    y_min = bbox.ymin
    y_max = bbox.ymax
    thickness = y_max - y_min

    # Recover the original Sketch4 bore from the two radius-10 circular edges.
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

    # Replace the existing bore rather than merely cutting inside it. A very
    # small radial overlap avoids coincident cylindrical faces during fusion.
    overlap = 0.02
    axial_margin = 0.10
    plug = cq.Solid.makeCylinder(
        bore_radius + overlap,
        thickness + 2.0 * axial_margin,
        cq.Vector(cx, y_min - axial_margin, cz),
        cq.Vector(0, 1, 0),
    )

    restored = base.fuse(plug)
    try:
        restored = restored.clean()
    except Exception:
        pass

    # Construct a regular hexagon inscribed in the recovered radius-10 circle.
    # The cutter extends beyond both thickness faces to implement Through All.
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

    result = restored.cut(hexagonal_cutter)
    try:
        result = result.clean()
    except Exception:
        pass

    print("Result valid:", result.isValid())
    print("Result solids:", len(result.Solids()))
    print("Result faces:", len(result.Faces()))
    print(
        "Hexagonal Through All cut: across corners=%.6f, across flats=%.6f"
        % (2.0 * bore_radius, (3.0 ** 0.5) * bore_radius)
    )

    return cq.Workplane("XY").newObject([result])