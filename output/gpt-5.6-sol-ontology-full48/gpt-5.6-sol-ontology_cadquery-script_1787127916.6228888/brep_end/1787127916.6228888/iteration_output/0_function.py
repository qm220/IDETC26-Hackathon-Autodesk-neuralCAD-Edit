def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    base = imported.val() if hasattr(imported, "val") else imported

    print(f"Loaded STEP: {input_file}")
    print(f"Valid: {base.isValid()}, solids: {len(base.Solids())}, faces: {len(base.Faces())}")
    bb = base.BoundingBox()
    print(f"Model bounds: x=({bb.xmin:.3f},{bb.xmax:.3f}), y=({bb.ymin:.3f},{bb.ymax:.3f}), z=({bb.zmin:.3f},{bb.zmax:.3f})")

    # Inspect and bind the planned FACE 7 to its actual imported geometry.
    terminal_candidates = []
    for index, face in enumerate(base.Faces()):
        fbb = face.BoundingBox()
        center = face.Center()
        geom = face.geomType()
        try:
            normal = face.normalAt(center)
            normal_text = f"({normal.x:.3f},{normal.y:.3f},{normal.z:.3f})"
        except Exception:
            normal = None
            normal_text = "unavailable"
        print(
            f"FACE {index}: {geom}, area={face.Area():.6f}, "
            f"center=({center.x:.3f},{center.y:.3f},{center.z:.3f}), "
            f"bounds=({fbb.xmin:.3f},{fbb.xmax:.3f})/({fbb.ymin:.3f},{fbb.ymax:.3f})/({fbb.zmin:.3f},{fbb.zmax:.3f}), "
            f"normal={normal_text}"
        )

        # FACE 7 is the planar 12 x 4 mm end face at the maximum X extent.
        if geom == "PLANE" and abs(fbb.xmax - fbb.xmin) < 1.0e-5 and abs(fbb.xmax - bb.xmax) < 1.0e-4:
            terminal_candidates.append((face.Area(), face))

    if not terminal_candidates:
        raise ValueError("Could not localize the planar unfilleted terminal face at maximum X")

    terminal_face = max(terminal_candidates, key=lambda item: item[0])[1]
    terminal_bb = terminal_face.BoundingBox()
    terminal_center = terminal_face.Center()
    axis_x = terminal_bb.xmax
    axis_y = terminal_center.y
    axis_z = terminal_center.z
    print(
        f"Bound target terminal face at x={axis_x:.6f}; "
        f"bearing axis passes through ({axis_x:.6f},{axis_y:.6f},{axis_z:.6f}) parallel to +X"
    )

    # Editable bearing parameters. Defaults follow the existing socket precedent:
    # 14 mm outside diameter, 10 mm bore diameter, and a 10 mm axial length.
    outer_radius = float(args.get("bearing_outer_radius", 7.0))
    bore_radius = float(args.get("bearing_bore_radius", 5.0))
    bearing_length = float(args.get("bearing_length", 10.0))
    occurrence_count = int(args.get("bearing_occurrences", 8))
    total_angle = float(args.get("pattern_angle", 360.0))

    if outer_radius <= bore_radius or bore_radius <= 0 or bearing_length <= 0:
        raise ValueError("Bearing dimensions must provide positive length and positive wall thickness")
    if occurrence_count != 8:
        print(f"Warning: request specifies 8 total occurrences; using supplied count {occurrence_count}")

    axis_start = cq.Vector(axis_x, axis_y, axis_z)
    axis_end = cq.Vector(axis_x + 1.0, axis_y, axis_z)
    axis_direction = cq.Vector(1.0, 0.0, 0.0)

    outer = cq.Solid.makeCylinder(outer_radius, bearing_length, axis_start, axis_direction)
    bore = cq.Solid.makeCylinder(bore_radius, bearing_length, axis_start, axis_direction)
    bearing = outer.cut(bore)
    print(
        f"Created sleeve bearing: OD={2*outer_radius:.3f}, ID={2*bore_radius:.3f}, "
        f"length={bearing_length:.3f} mm"
    )

    # A cylindrical bearing rotated about its own axis is coincident. To realize the
    # requested eight visible design instances, pattern the completed lever occurrence
    # around the common bearing axis and retain one shared annular bearing hub.
    patterned_body = base
    angle_step = total_angle / occurrence_count
    for occurrence in range(1, occurrence_count):
        angle = occurrence * angle_step
        rotated_body = base.rotate(axis_start, axis_end, angle)
        patterned_body = patterned_body.fuse(rotated_body)
        print(f"Created occurrence {occurrence + 1}/{occurrence_count} at {angle:.3f} degrees")

    result = patterned_body.fuse(bearing)
    result = result.clean()

    print(f"Pattern spacing: {angle_step:.3f} degrees about the bearing X-axis")
    print(f"Result valid: {result.isValid()}, solids: {len(result.Solids())}, volume: {result.Volume():.6f} mm^3")
    return cq.Workplane(obj=result)