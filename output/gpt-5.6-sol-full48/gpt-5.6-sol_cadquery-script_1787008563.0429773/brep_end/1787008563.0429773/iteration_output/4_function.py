def my_cad_function(args):
    import os
    import cadquery as cq
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Defeaturing

    imported = cq.importers.importStep(os.path.expanduser(args["input_file"]))
    original = imported.val().Solids()[0]

    target_faces = []
    for face in original.Faces():
        for edge in face.Edges():
            if edge.geomType() == "CIRCLE":
                try:
                    if abs(edge.radius() - 10.0) < 1.0e-4:
                        target_faces.append(face)
                        break
                except Exception:
                    pass

    if len(target_faces) != 8:
        raise RuntimeError("Expected 8 continuous R10 bullnose faces, found %d" % len(target_faces))

    annular_faces = [f for f in original.Faces() if f.geomType() == "PLANE" and len(f.Wires()) >= 2]
    rear_land = min(annular_faces, key=lambda f: f.Area())
    rear_normal = rear_land.normalAt()
    rear_center = rear_land.Center()
    rear_offset = rear_center.x * rear_normal.x + rear_center.y * rear_normal.y + rear_center.z * rear_normal.z

    defeature = BRepAlgoAPI_Defeaturing()
    defeature.SetShape(original.wrapped)
    for face in target_faces:
        defeature.AddFaceToRemove(face.wrapped)
    defeature.Build()
    if not defeature.IsDone():
        raise RuntimeError("Failed to remove and heal the R10 bullnose")

    healed = cq.Shape.cast(defeature.Shape()).clean().Solids()[0]
    if not healed.isValid():
        raise RuntimeError("Invalid solid after removing R10 bullnose")

    rear_candidates = []
    for face in healed.Faces():
        if face.geomType() != "PLANE" or len(face.Wires()) < 2:
            continue
        n = face.normalAt()
        c = face.Center()
        alignment = abs(n.x * rear_normal.x + n.y * rear_normal.y + n.z * rear_normal.z)
        offset_error = abs(c.x * rear_normal.x + c.y * rear_normal.y + c.z * rear_normal.z - rear_offset)
        if alignment > 0.999999 and offset_error < 1.0e-3:
            rear_candidates.append(face)

    if not rear_candidates:
        raise RuntimeError("Could not identify healed rear retaining land")

    healed_rear = max(rear_candidates, key=lambda f: f.Area())
    outer_wire = max(healed_rear.Wires(), key=lambda w: w.Length())
    perimeter_edges = outer_wire.Edges()
    if len(perimeter_edges) != 8:
        raise RuntimeError("Expected 8 perimeter edges, found %d" % len(perimeter_edges))

    result = healed.fillet(2.0, perimeter_edges).clean().Solids()[0]
    if not result.isValid():
        raise RuntimeError("Invalid solid after applying replacement R2 fillet")

    return cq.Workplane("XY").newObject([result])