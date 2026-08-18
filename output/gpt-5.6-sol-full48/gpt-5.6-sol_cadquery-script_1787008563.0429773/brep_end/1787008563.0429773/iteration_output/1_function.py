def my_cad_function(args):
    import os
    import cadquery as cq
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Defeaturing

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    original = model.val()

    # Identify the continuous R10 outer bullnose. Its eight faces are the
    # cylindrical/toroidal faces bounded by transverse circular R10 edges.
    target_faces = []
    for face in original.Faces():
        has_r10_edge = False
        for edge in face.Edges():
            if edge.geomType() == "CIRCLE":
                try:
                    if abs(edge.radius() - 10.0) < 1.0e-4:
                        has_r10_edge = True
                        break
                except Exception:
                    pass
        if has_r10_edge:
            target_faces.append(face)

    print("R10 bullnose faces selected:", len(target_faces))
    if len(target_faces) != 8:
        raise RuntimeError(
            "Expected 8 connected R10 bullnose faces, found %d" % len(target_faces)
        )

    # Record the plane of the narrow rear retaining land. It is the smaller
    # of the two planar annular faces and is adjacent to the bullnose side.
    annular_faces = [
        f for f in original.Faces()
        if f.geomType() == "PLANE" and len(f.Wires()) >= 2
    ]
    if len(annular_faces) < 2:
        raise RuntimeError("Could not identify the front and rear annular lands")

    rear_land = min(annular_faces, key=lambda f: f.Area())
    rear_normal = rear_land.normalAt()
    rear_center = rear_land.Center()
    rear_plane_offset = (
        rear_center.x * rear_normal.x
        + rear_center.y * rear_normal.y
        + rear_center.z * rear_normal.z
    )
    print("Rear land area before healing:", rear_land.Area())

    # Remove the complete R10 face set and heal the adjoining rear-land and
    # outer-wall support surfaces to their sharp intersection.
    defeature = BRepAlgoAPI_Defeaturing()
    defeature.SetShape(original.wrapped)
    for face in target_faces:
        defeature.AddFace(face.wrapped)
    defeature.Build()

    if not defeature.IsDone():
        raise RuntimeError("OCCT failed to remove and heal the R10 bullnose")

    healed = cq.Shape.cast(defeature.Shape()).clean()
    if not healed.isValid():
        raise RuntimeError("The healed sharp-corner solid is invalid")

    print("After R10 removal: faces=%d edges=%d valid=%s" % (
        len(healed.Faces()), len(healed.Edges()), healed.isValid()
    ))

    # Find the healed rear-land plane by its stored plane equation.
    healed_rear_candidates = []
    for face in healed.Faces():
        if face.geomType() != "PLANE" or len(face.Wires()) < 2:
            continue
        n = face.normalAt()
        alignment = abs(
            n.x * rear_normal.x + n.y * rear_normal.y + n.z * rear_normal.z
        )
        fc = face.Center()
        plane_error = abs(
            fc.x * rear_normal.x
            + fc.y * rear_normal.y
            + fc.z * rear_normal.z
            - rear_plane_offset
        )
        if alignment > 0.999999 and plane_error < 1.0e-3:
            healed_rear_candidates.append(face)

    if not healed_rear_candidates:
        raise RuntimeError("Could not find the healed rear retaining-land face")

    healed_rear = max(healed_rear_candidates, key=lambda f: f.Area())
    wires = healed_rear.Wires()
    outer_wire = max(wires, key=lambda w: w.Length())
    perimeter_edges = outer_wire.Edges()

    print("Replacement perimeter edge count:", len(perimeter_edges))
    print("Replacement perimeter length:", outer_wire.Length())

    # Replace the removed R10 feature with the common profile radius R2 over
    # the same complete outer perimeter loop.
    result = healed.makeFillet(2.0, perimeter_edges).clean()

    if not result.isValid() or len(result.Solids()) != 1:
        raise RuntimeError("The replacement R2 perimeter fillet is not a valid single solid")

    r10_edges = 0
    r2_edges = 0
    for edge in result.Edges():
        if edge.geomType() != "CIRCLE":
            continue
        try:
            radius = edge.radius()
            if abs(radius - 10.0) < 1.0e-4:
                r10_edges += 1
            if abs(radius - 2.0) < 1.0e-4:
                r2_edges += 1
        except Exception:
            pass

    print("FINAL VALID", result.isValid())
    print("FINAL VOLUME %.6f" % result.Volume())
    print("FINAL COUNTS solids=%d faces=%d edges=%d" % (
        len(result.Solids()), len(result.Faces()), len(result.Edges())
    ))
    print("FINAL circular R10 edges:", r10_edges)
    print("FINAL circular R2 edges:", r2_edges)

    return cq.Workplane("XY").newObject([result])