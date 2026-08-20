def my_cad_function(args):
    import os
    import cadquery as cq
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Defeaturing

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    print("INPUT VALID:", shape.isValid())
    print("INPUT SOLIDS:", len(shape.Solids()), "FACES:", len(shape.Faces()))

    if not shape.isValid() or len(shape.Solids()) != 1:
        raise RuntimeError("Input STEP must contain one valid solid")

    source_faces = shape.Faces()
    if len(source_faces) < 43:
        raise RuntimeError("Expected at least 43 faces in the grounded input model")

    # Bind the planning face indices to the imported STEP geometry. F005 is
    # the continuous radius-10 transition represented by FACE 35..FACE 42.
    target_indices = list(range(35, 43))
    target_faces = [source_faces[i] for i in target_indices]

    print("Grounded F005 faces:", target_indices)
    for i, face in zip(target_indices, target_faces):
        c = face.Center()
        print("  FACE %d type=%s area=%.6f center=(%.4f, %.4f, %.4f)" % (
            i, face.geomType(), face.Area(), c.x, c.y, c.z))

    target_types = [f.geomType() for f in target_faces]
    if target_types.count("TORUS") != 4 or target_types.count("CYLINDER") != 4:
        raise RuntimeError(
            "FACE 35..42 do not match the expected four toroidal and four cylindrical F005 faces"
        )

    # Capture the actual plane of grounded F004 before topology changes.
    source_land = source_faces[34]
    if source_land.geomType() != "PLANE" or len(source_land.Wires()) < 2:
        raise RuntimeError("Grounded FACE 34 is not the expected annular planar F004 land")

    land_center = source_land.Center()
    land_normal = source_land.normalAt(land_center).normalized()
    print("Grounded F004 area=%.6f wires=%d center=(%.4f, %.4f, %.4f) normal=(%.8f, %.8f, %.8f)" % (
        source_land.Area(), len(source_land.Wires()),
        land_center.x, land_center.y, land_center.z,
        land_normal.x, land_normal.y, land_normal.z))

    # Remove the entire radius-10 loop and allow OCCT to extend its neighboring
    # outer wall and mounting-land faces until they meet at a sharp loop.
    defeature = BRepAlgoAPI_Defeaturing()
    defeature.SetShape(shape.wrapped)

    if hasattr(defeature, "AddFaceToRemove"):
        for face in target_faces:
            defeature.AddFaceToRemove(face.wrapped)
    elif hasattr(defeature, "AddFacesToRemove"):
        from OCP.TopTools import TopTools_ListOfShape
        face_list = TopTools_ListOfShape()
        for face in target_faces:
            face_list.Append(face.wrapped)
        defeature.AddFacesToRemove(face_list)
    elif hasattr(defeature, "SetFacesToRemove"):
        from OCP.TopTools import TopTools_ListOfShape
        face_list = TopTools_ListOfShape()
        for face in target_faces:
            face_list.Append(face.wrapped)
        defeature.SetFacesToRemove(face_list)
    else:
        raise RuntimeError("Installed OCCT defeaturing API exposes no supported face-removal method")

    defeature.Build()
    if not defeature.IsDone():
        raise RuntimeError("OCCT could not remove the continuous F005 radius-10 loop")

    restored = cq.Shape.cast(defeature.Shape())
    print("DEFEATURED VALID:", restored.isValid(),
          "SOLIDS:", len(restored.Solids()), "FACES:", len(restored.Faces()))

    if not restored.isValid() or len(restored.Solids()) != 1:
        raise RuntimeError("Removing F005 did not produce one valid solid")

    # Relocate F004 by its captured plane and annular topology, avoiding any
    # dependence on face numbering after defeaturing.
    land_candidates = []
    for i, face in enumerate(restored.Faces()):
        if face.geomType() != "PLANE" or len(face.Wires()) < 2:
            continue
        c = face.Center()
        try:
            n = face.normalAt(c).normalized()
        except Exception:
            continue

        alignment = abs(n.dot(land_normal))
        plane_distance = abs((c - land_center).dot(land_normal))
        if alignment > 0.999 and plane_distance < 0.05:
            land_candidates.append((face.Area(), i, face, alignment, plane_distance))

    if not land_candidates:
        raise RuntimeError("Could not locate restored F004 annular mounting land")

    # The restored F004 should have gained area when the radius-10 blend was
    # removed. Choose the largest coplanar annular candidate deterministically.
    land_candidates.sort(key=lambda item: item[0], reverse=True)
    _, land_index, mounting_land, alignment, plane_distance = land_candidates[0]
    print("RESTORED F004 face=%d area=%.6f wires=%d alignment=%.9f plane_distance=%.9f" % (
        land_index, mounting_land.Area(), len(mounting_land.Wires()),
        alignment, plane_distance))

    # F004 has an inner and an outer wire. The longer wire is the outer sharp
    # boundary created where F004 and F001 were extended to meet. This is the
    # exact loop formerly occupied by F005.
    wire_data = []
    for i, wire in enumerate(mounting_land.Wires()):
        bb = wire.BoundingBox()
        span = bb.xlen + bb.ylen + bb.zlen
        wire_data.append((wire.Length(), span, i, wire))
        print("  F004 WIRE %d length=%.6f span=%.6f edges=%d" % (
            i, wire.Length(), span, len(wire.Edges())))

    wire_data.sort(key=lambda item: (item[0], item[1]), reverse=True)
    outer_wire = wire_data[0][3]
    replacement_edges = outer_wire.Edges()

    if len(replacement_edges) != 8:
        raise RuntimeError(
            "Expected 8 edges around the restored rounded-rectangular outer loop; got %d" %
            len(replacement_edges)
        )

    print("Applying replacement radius 2.0 mm to restored F005 boundary")
    for i, edge in enumerate(replacement_edges):
        c = edge.Center()
        print("  EDGE %d type=%s length=%.6f center=(%.4f, %.4f, %.4f)" % (
            i, edge.geomType(), edge.Length(), c.x, c.y, c.z))

    edited = restored.makeFillet(2.0, replacement_edges)

    if not edited.isValid() or len(edited.Solids()) != 1:
        raise RuntimeError("Replacement radius-2 fillet did not produce one valid solid")

    print("OUTPUT VALID:", edited.isValid())
    print("OUTPUT SOLIDS:", len(edited.Solids()),
          "FACES:", len(edited.Faces()), "EDGES:", len(edited.Edges()))
    print("OUTPUT VOLUME: %.6f" % edited.Volume())

    # Report all curved surfaces so the resulting transition can be checked.
    curved = []
    for i, face in enumerate(edited.Faces()):
        if face.geomType() in ("CYLINDER", "TORUS"):
            c = face.Center()
            curved.append((i, face.geomType(), face.Area(), c.x, c.y, c.z))
    print("OUTPUT CURVED FACES:")
    for item in curved:
        print("  FACE %d type=%s area=%.6f center=(%.4f, %.4f, %.4f)" % item)

    return cq.Workplane(obj=edited)
