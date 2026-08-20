def my_cad_function(args):
    import os
    import math

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    body = imported.val() if hasattr(imported, "val") else imported

    print(f"Loaded STEP: {input_file}")
    print(f"Valid before edit: {body.isValid()}")
    print(f"Solids before edit: {len(body.Solids())}")
    print(f"Faces before edit: {len(body.Faces())}")

    # Bind the planned ring-bore face to the imported STEP geometry rather
    # than relying solely on the historical FACE 21 index.
    target_face = None
    target_score = float("inf")
    for index, face in enumerate(body.Faces()):
        bb = face.BoundingBox()
        center = bb.center
        geom_type = face.geomType()
        print(
            f"FACE {index}: type={geom_type}, "
            f"center=({center.x:.6f},{center.y:.6f},{center.z:.6f}), "
            f"bbox=({bb.xmin:.6f},{bb.xmax:.6f}) "
            f"({bb.ymin:.6f},{bb.ymax:.6f}) "
            f"({bb.zmin:.6f},{bb.zmax:.6f}), area={face.Area():.6f}"
        )

        if geom_type == "CYLINDER":
            x_span = bb.xmax - bb.xmin
            y_span = bb.ymax - bb.ymin
            z_span = bb.zmax - bb.zmin
            score = (
                abs(center.x)
                + abs(center.z - 10.0)
                + abs(x_span - 20.0)
                + abs(z_span - 20.0)
                + abs(y_span - 15.0)
            )
            if score < target_score:
                target_score = score
                target_face = face

    if target_face is None:
        raise ValueError("Could not locate the ring-end cylindrical bore face")

    bore_bb = target_face.BoundingBox()
    center_x = 0.5 * (bore_bb.xmin + bore_bb.xmax)
    center_z = 0.5 * (bore_bb.zmin + bore_bb.zmax)
    radius_x = 0.5 * (bore_bb.xmax - bore_bb.xmin)
    radius_z = 0.5 * (bore_bb.zmax - bore_bb.zmin)
    radius = 0.5 * (radius_x + radius_z)
    y_min = bore_bb.ymin
    y_max = bore_bb.ymax
    thickness = y_max - y_min

    print(
        f"Bound bore: center XZ=({center_x:.6f},{center_z:.6f}), "
        f"radius={radius:.6f}, Y=({y_min:.6f},{y_max:.6f})"
    )

    if target_score > 0.1 or abs(radius - 10.0) > 0.05 or abs(thickness - 15.0) > 0.05:
        raise ValueError("Located face does not match the expected Sketch4 ring bore")

    # Restore the material removed by the original cylindrical through-hole.
    plug = cq.Solid.makeCylinder(
        radius,
        thickness,
        cq.Vector(center_x, y_min, center_z),
        cq.Vector(0, 1, 0),
    )
    restored = body.fuse(plug).clean()

    # Explicitly construct all six vertices in 3D. This avoids the prior
    # workplane/polyline behavior that produced a five-sided opening.
    margin = 1.0
    cutter_start_y = y_min - margin
    cutter_length = thickness + 2.0 * margin
    vertices = []
    for i in range(6):
        angle = 2.0 * math.pi * i / 6.0
        vertices.append(
            cq.Vector(
                center_x + radius * math.cos(angle),
                cutter_start_y,
                center_z + radius * math.sin(angle),
            )
        )

    hex_wire = cq.Wire.makePolygon(vertices, close=True)
    if len(hex_wire.Edges()) != 6:
        raise ValueError(f"Hexagonal profile has {len(hex_wire.Edges())} edges instead of 6")

    hex_cutter = cq.Solid.extrudeLinear(
        hex_wire,
        [],
        cq.Vector(0, cutter_length, 0),
    )
    result_shape = restored.cut(hex_cutter).clean()

    expected_hex_area = (3.0 * math.sqrt(3.0) / 2.0) * radius * radius
    print(f"Hex profile edge count: {len(hex_wire.Edges())}")
    print(f"Hexagon circumradius: {radius:.6f}")
    print(f"Hexagon side length: {radius:.6f}")
    print(f"Hexagon across corners: {2.0 * radius:.6f}")
    print(f"Hexagon across flats: {math.sqrt(3.0) * radius:.6f}")
    print(f"Expected profile area: {expected_hex_area:.6f} mm^2")
    print(f"Valid after edit: {result_shape.isValid()}")
    print(f"Solids after edit: {len(result_shape.Solids())}")
    print(f"Faces after edit: {len(result_shape.Faces())}")
    print(f"Volume after edit: {result_shape.Volume():.6f} mm^3")

    if not result_shape.isValid():
        raise ValueError("Resulting edited wrench is invalid")
    if len(result_shape.Solids()) != 1:
        raise ValueError("Expected one connected solid after the edit")

    return cq.Workplane("XY").newObject([result_shape])