def my_cad_function(args):
    import os
    from OCP.BRepAdaptor import BRepAdaptor_Surface

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    base_shape = imported.val() if hasattr(imported, "val") else imported
    bbox = base_shape.BoundingBox()

    # Locate the radius-3 cylindrical surfaces and select the one nearest
    # the negative-X end, corresponding to the clevis pivot bore.
    bore_candidates = []
    for face in base_shape.Faces():
        if face.geomType() != "CYLINDER":
            continue
        try:
            adaptor = BRepAdaptor_Surface(face.wrapped)
            cylinder = adaptor.Cylinder()
            radius = cylinder.Radius()
            if abs(radius - 3.0) > 0.20:
                continue

            location = cylinder.Location()
            direction = cylinder.Axis().Direction()
            bore_candidates.append({
                "radius": radius,
                "location": (location.X(), location.Y(), location.Z()),
                "direction": (direction.X(), direction.Y(), direction.Z()),
                "face_center_x": face.Center().x
            })
        except Exception:
            continue

    if not bore_candidates:
        raise ValueError("Could not locate the cylindrical clevis bearing bore")

    pivot = min(bore_candidates, key=lambda item: item["face_center_x"])
    px, py, pz = pivot["location"]
    dx, dy, dz = pivot["direction"]

    # Snap the detected cylindrical axis to its dominant model axis. The
    # supplied part has a Y-directed clevis pin axis.
    components = [abs(dx), abs(dy), abs(dz)]
    axis_index = components.index(max(components))

    if axis_index == 0:
        start = cq.Vector(bbox.xmin, py, pz)
        pin_direction = cq.Vector(1, 0, 0)
        pin_length = bbox.xmax - bbox.xmin
        axis_name = "X"
    elif axis_index == 1:
        start = cq.Vector(px, bbox.ymin, pz)
        pin_direction = cq.Vector(0, 1, 0)
        pin_length = bbox.ymax - bbox.ymin
        axis_name = "Y"
    else:
        start = cq.Vector(px, py, bbox.zmin)
        pin_direction = cq.Vector(0, 0, 1)
        pin_length = bbox.zmax - bbox.zmin
        axis_name = "Z"

    # Use a small running clearance relative to the nominal 6 mm bore.
    # The pin remains an independent solid so the lever can rotate about it.
    pin_radius = 2.95
    pin = cq.Solid.makeCylinder(pin_radius, pin_length, start, pin_direction)

    result = cq.Assembly(name="lever_with_pivot_pin")
    result.add(base_shape, name="original_lever")
    result.add(pin, name="pivot_pin")

    print("Detected pivot axis: %s" % axis_name)
    print("Pivot centerline reference: (%.4f, %.4f, %.4f) mm" % (px, py, pz))
    print("Created separate pivot pin: diameter %.3f mm, length %.3f mm" % (2.0 * pin_radius, pin_length))
    print("Original lever geometry was preserved without fusion to the pin")
    return result