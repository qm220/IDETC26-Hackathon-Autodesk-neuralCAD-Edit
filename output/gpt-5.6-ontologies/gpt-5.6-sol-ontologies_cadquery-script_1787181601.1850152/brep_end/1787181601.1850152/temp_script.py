def my_cad_function(args):
    import os
    import math

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    # Locate the original cylindrical through-hole. In this model it is the
    # cylindrical face with two complete circular edges and one seam edge.
    target_face = None
    target_radius = None
    circle_centers = None

    for face in shape.Faces():
        try:
            if face.geomType() != "CYLINDER":
                continue
        except Exception:
            continue

        complete_circles = []
        for edge in face.Edges():
            try:
                if edge.geomType() != "CIRCLE":
                    continue
                radius = edge.radius()
                if abs(edge.Length() - 2.0 * math.pi * radius) < 1.0e-4:
                    complete_circles.append((edge, radius))
            except Exception:
                pass

        # The requested bore has exactly two full circular boundary edges.
        if len(complete_circles) == 2:
            r0 = complete_circles[0][1]
            r1 = complete_circles[1][1]
            if abs(r0 - r1) < 1.0e-5:
                centers = [complete_circles[0][0].Center(),
                           complete_circles[1][0].Center()]
                separation = (centers[1] - centers[0]).Length
                if abs(separation - 15.0) < 1.0e-3 and abs(r0 - 10.0) < 1.0e-3:
                    target_face = face
                    target_radius = r0
                    circle_centers = centers
                    break

    if target_face is None:
        raise ValueError("Could not identify the original Sketch4 cylindrical through-hole")

    c0, c1 = circle_centers
    ymin = min(c0.y, c1.y)
    ymax = max(c0.y, c1.y)
    thickness = ymax - ymin
    cx = 0.5 * (c0.x + c1.x)
    cz = 0.5 * (c0.z + c1.z)

    print("Original hole center: (%.6f, %.6f), radius: %.6f, y extent: [%.6f, %.6f]" %
          (cx, cz, target_radius, ymin, ymax))

    # Refill the original circular opening. A tiny radial overlap ensures a
    # robust union with the surrounding ring without changing its exterior.
    fill = cq.Solid.makeCylinder(
        target_radius + 0.05,
        thickness,
        cq.Vector(cx, ymin, cz),
        cq.Vector(0, 1, 0)
    )
    restored = shape.fuse(fill)

    # Construct a regular hexagon whose six vertices lie on the original
    # radius-10 circular boundary. The cutting prism extends beyond both
    # thickness faces, giving an unambiguous through-all cut.
    hex_points = []
    for i in range(6):
        angle = 2.0 * math.pi * i / 6.0
        hex_points.append((target_radius * math.cos(angle),
                           target_radius * math.sin(angle)))

    cutting_plane = cq.Plane(
        origin=(cx, ymin - 1.0, cz),
        xDir=(1, 0, 0),
        normal=(0, 1, 0)
    )
    hex_tool = (cq.Workplane(cutting_plane)
                .polyline(hex_points)
                .close()
                .extrude(thickness + 2.0)
                .val())

    result = restored.cut(hex_tool).clean()

    print("Result valid:", result.isValid())
    print("Result solids:", len(result.Solids()), "faces:", len(result.Faces()))
    print("Created six-sided inscribed through-all cutout at the original hole location")

    if not result.isValid() or len(result.Solids()) != 1:
        raise ValueError("Hexagonal hole replacement produced an invalid or non-single-solid result")

    return cq.Workplane(obj=result)
