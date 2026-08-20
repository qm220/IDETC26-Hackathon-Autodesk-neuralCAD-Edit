def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    source_shape = imported.val()

    candidates = []
    for face in source_shape.Faces():
        try:
            vertices = face.Vertices()
            if not vertices or face.geomType() != "PLANE":
                continue

            z_values = [v.Center().z for v in vertices]
            center = face.Center()
            area = face.Area()
            edge_count = len(face.outerWire().Edges())

            if max(z_values) - min(z_values) < 1.0e-5 and abs(center.z + 10.0) < 0.1:
                candidates.append((face, area, edge_count))
        except Exception:
            continue

    if not candidates:
        raise ValueError("Could not locate the existing vertical slot pocket floor")

    capsule_candidates = [item for item in candidates if item[2] == 4]
    pocket_face = min(
        capsule_candidates if capsule_candidates else candidates,
        key=lambda item: item[1]
    )[0]

    slot_wire = pocket_face.outerWire()
    cutter_front = cq.Solid.extrudeLinear(
        slot_wire, [], cq.Vector(0.0, 0.0, 100.0)
    )
    cutter_rear = cq.Solid.extrudeLinear(
        slot_wire, [], cq.Vector(0.0, 0.0, -100.0)
    )
    result_shape = source_shape.cut(cutter_front.fuse(cutter_rear))

    if not result_shape.isValid():
        raise ValueError("The through-slot operation produced an invalid shape")

    return cq.Workplane("XY").newObject([result_shape])