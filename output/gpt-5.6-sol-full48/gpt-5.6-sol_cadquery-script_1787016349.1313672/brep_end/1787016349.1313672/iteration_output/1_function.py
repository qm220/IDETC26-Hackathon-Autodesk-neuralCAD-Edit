def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    base_shape = imported.val() if hasattr(imported, "val") else imported

    bbox = base_shape.BoundingBox()
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
    else:
        end_x = bbox.xmax
        center_y = 0.5 * (bbox.ymin + bbox.ymax)
        center_z = 0.5 * (bbox.zmin + bbox.zmax)

    bearing_outer_radius = 7.0
    bearing_bore_radius = 5.0
    bearing_length = 14.0
    origin = cq.Vector(end_x, center_y, center_z)
    axis = cq.Vector(1, 0, 0)

    outer = cq.Solid.makeCylinder(bearing_outer_radius, bearing_length, origin, axis)
    bore = cq.Solid.makeCylinder(bearing_bore_radius, bearing_length, origin, axis)
    bearing = outer.cut(bore)
    seed = base_shape.fuse(bearing).clean()

    axis_start = cq.Vector(end_x, center_y, center_z)
    axis_end = cq.Vector(end_x + 1.0, center_y, center_z)
    instances = [
        seed if i == 0 else seed.rotate(axis_start, axis_end, 45.0 * i)
        for i in range(8)
    ]

    result = cq.Compound.makeCompound(instances)
    print("Operation finished: terminal cylindrical bearing created and eight total design instances patterned at 45-degree intervals about its axis.")
    return result