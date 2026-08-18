def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    base_shape = imported.val() if hasattr(imported, "val") else imported

    bbox = base_shape.BoundingBox()
    print("Input valid:", base_shape.isValid())
    print("Input bounding box: x=[%.3f, %.3f], y=[%.3f, %.3f], z=[%.3f, %.3f]" % (
        bbox.xmin, bbox.xmax, bbox.ymin, bbox.ymax, bbox.zmin, bbox.zmax
    ))

    # Locate the largest planar face at the maximum-X, non-rounded end.
    tolerance = 1.0e-3
    terminal_faces = []
    for face in base_shape.Faces():
        center = face.Center()
        try:
            geom_type = face.geomType()
        except Exception:
            geom_type = ""
        if geom_type == "PLANE" and abs(center.x - bbox.xmax) < tolerance:
            terminal_faces.append(face)

    if terminal_faces:
        terminal_face = max(terminal_faces, key=lambda f: f.Area())
        terminal_center = terminal_face.Center()
        end_x = bbox.xmax
        center_y = terminal_center.y
        center_z = terminal_center.z
        print("Terminal face found at x=%.3f, center=(%.3f, %.3f, %.3f), area=%.3f" % (
            end_x, terminal_center.x, center_y, center_z, terminal_face.Area()
        ))
    else:
        # Dimensional fallback from the supplied model description.
        end_x = bbox.xmax
        center_y = 0.5 * (bbox.ymin + bbox.ymax)
        center_z = 0.5 * (bbox.zmin + bbox.zmax)
        print("Terminal face selection fallback used; center=(%.3f, %.3f, %.3f)" % (
            end_x, center_y, center_z
        ))

    # Match the existing boss precedent: OD 14 mm, bore diameter 10 mm.
    # Use a 14 mm outward axial length because no separate length was supplied.
    bearing_outer_radius = 7.0
    bearing_bore_radius = 5.0
    bearing_length = 14.0
    origin = cq.Vector(end_x, center_y, center_z)
    axis = cq.Vector(1, 0, 0)

    outer = cq.Solid.makeCylinder(
        bearing_outer_radius, bearing_length, origin, axis
    )
    bore = cq.Solid.makeCylinder(
        bearing_bore_radius, bearing_length, origin, axis
    )
    bearing = outer.cut(bore)

    # Join the annular bearing housing to the square terminal face.
    try:
        seed = base_shape.fuse(bearing).clean()
        if not seed.isValid():
            raise ValueError("Fused seed is invalid")
        print("Bearing successfully joined to terminal face.")
    except Exception as exc:
        print("Bearing fusion fallback used:", exc)
        seed = cq.Compound.makeCompound([base_shape, bearing])

    # Eight total linked geometric occurrences: seed plus seven additional
    # instances at 45-degree intervals about the terminal bearing axis.
    axis_start = cq.Vector(end_x, center_y, center_z)
    axis_end = cq.Vector(end_x + 1.0, center_y, center_z)
    instances = []
    for index in range(8):
        angle = 45.0 * index
        occurrence = seed if index == 0 else seed.rotate(axis_start, axis_end, angle)
        instances.append(occurrence)

    result = cq.Compound.makeCompound(instances)
    print("Created cylindrical terminal bearing and 8 total occurrences.")
    print("Pattern angles:", [45 * i for i in range(8)])
    print("Result valid:", result.isValid())
    return result