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

    # Inspect and bind the planned FACE 21 to its actual imported geometry.
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

        # The intended bore is the Y-directed cylindrical face centered at
        # X=0, Z=10, spanning X/Z by 20 mm and Y by the full 15 mm thickness.
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
    bore_center_x = 0.5 * (bore_bb.xmin + bore_bb.xmax)
    bore_center_z = 0.5 * (bore_bb.zmin + bore_bb.zmax)
    bore_radius = 0.25 * (
        (bore_bb.xmax - bore_bb.xmin) + (bore_bb.zmax - bore_bb.zmin)
    )
    y_min = bore_bb.ymin
    y_max = bore_bb.ymax
    thickness = y_max - y_min

    print(
        "Bound ring bore: "
        f"center=({bore_center_x:.6f}, {bore_center_z:.6f}) in XZ, "
        f"radius={bore_radius:.6f}, Y=({y_min:.6f},{y_max:.6f})"
    )

    if abs(bore_radius - 10.0) > 0.05 or abs(thickness - 15.0) > 0.05:
        raise ValueError("Located cylindrical face does not match the planned radius-10 through bore")

    # Imported STEP geometry has no editable feature history. Restore the
    # original circular opening with a coaxial plug before making the smaller
    # inscribed-hexagon cut.
    plug = cq.Solid.makeCylinder(
        bore_radius,
        thickness,
        cq.Vector(bore_center_x, y_min, bore_center_z),
        cq.Vector(0, 1, 0),
    )
    restored = body.fuse(plug).clean()

    # Construct a regular hexagon whose six vertices lie on the former bore
    # circle. The custom plane is normal to +Y. One vertex is aligned to the
    # stable local X axis; circumradius is exactly the original bore radius.
    margin = 1.0
    sketch_plane = cq.Plane(
        origin=(bore_center_x, y_min - margin, bore_center_z),
        xDir=(1, 0, 0),
        normal=(0, 1, 0),
    )
    points = []
    for i in range(6):
        angle = 2.0 * math.pi * i / 6.0
        points.append((bore_radius * math.cos(angle), bore_radius * math.sin(angle)))

    hex_cutter_wp = (
        cq.Workplane(sketch_plane)
        .moveTo(points[0][0], points[0][1])
        .polyline(points[1:])
        .close()
        .extrude(thickness + 2.0 * margin)
    )
    hex_cutter = hex_cutter_wp.val()

    result_shape = restored.cut(hex_cutter).clean()

    print(f"Hexagon circumradius: {bore_radius:.6f}")
    print(f"Hexagon side length: {bore_radius:.6f}")
    print(f"Hexagon across corners: {2.0 * bore_radius:.6f}")
    print(f"Hexagon across flats: {math.sqrt(3.0) * bore_radius:.6f}")
    print(f"Valid after edit: {result_shape.isValid()}")
    print(f"Solids after edit: {len(result_shape.Solids())}")
    print(f"Faces after edit: {len(result_shape.Faces())}")
    print(f"Volume after edit: {result_shape.Volume():.6f} mm^3")

    if not result_shape.isValid():
        raise ValueError("Resulting edited wrench is invalid")
    if len(result_shape.Solids()) != 1:
        raise ValueError("Expected one connected solid after the edit")

    return cq.Workplane("XY").newObject([result_shape])