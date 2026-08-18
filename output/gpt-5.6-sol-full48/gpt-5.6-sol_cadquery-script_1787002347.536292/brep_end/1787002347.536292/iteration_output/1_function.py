def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model_wp = cq.importers.importStep(input_file)
    model = model_wp.val()

    bbox = model.BoundingBox()

    candidates = []
    for face in model.Faces():
        try:
            if face.geomType() != "PLANE":
                continue
            center = face.Center()
            normal = face.normalAt(center)
            if abs(abs(normal.z) - 1.0) > 1.0e-5:
                continue
            edge_types = [edge.geomType() for edge in face.outerWire().Edges()]
            if abs(center.z + 10.0) < 0.05:
                line_count = sum(1 for kind in edge_types if kind == "LINE")
                circle_count = sum(1 for kind in edge_types if kind == "CIRCLE")
                if line_count == 2 and circle_count == 2:
                    candidates.append(face)
        except Exception:
            pass

    if not candidates:
        raise ValueError("Could not identify the front vertical-slot floor")

    slot_floor = min(candidates, key=lambda face: face.Area())
    cutter_wire = slot_floor.outerWire().translate(cq.Vector(0, 0, 0.5))
    cut_distance = (bbox.zmax - bbox.zmin) + 20.0
    cutter = cq.Solid.extrudeLinear(
        cutter_wire,
        [],
        cq.Vector(0, 0, -cut_distance)
    )

    edited = model.cut(cutter)

    if not edited.isValid():
        raise ValueError("Through-slot Boolean produced an invalid result")
    if edited.Volume() >= model.Volume():
        raise ValueError("Through-slot operation did not decrease model volume")
    if len(edited.Solids()) != 1:
        raise ValueError("Through-slot operation did not preserve one bracket solid")

    return cq.Workplane(obj=edited)