def my_cad_function(args):
    import os
    import cadquery as cq
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Defeaturing
    from OCP.TopTools import TopTools_ListOfShape

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

    # Bind F005 to the actual imported STEP topology. FACE 35..42 are the
    # continuous radius-10 transition: four toroidal corner surfaces and four
    # cylindrical straight surfaces extending around the complete perimeter.
    target_indices = list(range(35, 43))
    target_faces = [source_faces[i] for i in target_indices]

    print("Grounded F005 faces:", target_indices)
    for i, face in zip(target_indices, target_faces):
        c = face.Center()
        print("  FACE %d type=%s area=%.6f center=(%.4f, %.4f, %.4f)" % (
            i, face.geomType(), face.Area(), c.x, c.y, c.z))

    target_types = [face.geomType() for face in target_faces]
    if target_types.count("TORUS") != 4 or target_types.count("CYLINDER") != 4:
        raise RuntimeError(
            "FACE 35..42 do not match the expected continuous F005 radius-10 loop"
        )

    # Capture the mounting-land plane before defeaturing so it can be found
    # geometrically after OCCT renumbers the topology.
    source_land = source_faces[34]
    if source_land.geomType() != "PLANE" or len(source_land.Wires()) < 2:
        raise RuntimeError("Grounded FACE 34 is not the expected annular F004 land")

    land_center = source_land.Center()
    land_normal = source_land.normalAt(land_center).normalized()
    print("Grounded F004 area=%.6f wires=%d center=(%.4f, %.4f, %.4f) normal=(%.8f, %.8f, %.8f)" % (
        source_land.Area(), len(source_land.Wires()),
        land_center.x, land_center.y, land_center.z,
        land_normal.x, land_normal.y, land_normal.z))

    # Remove every constituent face of the large circumferential radius. OCCT
    # extends its neighboring wall and land until they meet at a sharp loop.
    defeature = BRepAlgoAPI_Defeaturing()
    defeature.SetShape(shape.wrapped)

    if hasattr(defeature, "AddFaceToRemove"):
        for face in target_faces:
            defeature.AddFaceToRemove(face.wrapped)
    else:
        faces_to_remove = TopTools_ListOfShape()
        for face in target_faces:
            faces_to_remove.Append(face.wrapped)

        if hasattr(defeature, "AddFacesToRemove"):
            defeature.AddFacesToRemove(faces_to_remove)
        elif hasattr(defeature, "SetFacesToRemove"):
            defeature.SetFacesToRemove(faces_to_remove)
        else:
            raise RuntimeError("Installed OCCT exposes no supported defeaturing face API")

    defeature.Build()
    if not defeature.IsDone():
        raise RuntimeError("OCCT could not remove the continuous F005 radius-10 loop")

    restored_shape = cq.Shape.cast(defeature.Shape())
    restored_solids = restored_shape.Solids()
    print("DEFEATURED VALID:", restored_shape.isValid(),
          "SOLIDS:", len(restored_solids), "FACES:", len(restored_shape.Faces()))

    if not restored_shape.isValid() or len(restored_solids) != 1:
        raise RuntimeError("Removing F005 did not produce one valid solid")

    restored_solid = restored_solids[0]

    # Relocate the enlarged F004 planar annulus using its original plane and
    # normal instead of relying on post-operation face indices.
    land_candidates = []
    for i, face in enumerate(restored_solid.Faces()):
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
            land_candidates.append(
                (face.Area(), i, face, alignment, plane_distance)
            )

    if not land_candidates:
        raise RuntimeError("Could not locate restored F004 annular mounting land")

    land_candidates.sort(key=lambda item: item[0], reverse=True)
    _, land_index, mounting_land, alignment, plane_distance = land_candidates[0]
    print("RESTORED F004 face=%d area=%.6f wires=%d alignment=%.9f plane_distance=%.9f" % (
        land_index, mounting_land.Area(), len(mounting_land.Wires()),
        alignment, plane_distance))

    # F004 has inner and outer boundary wires. The longer perimeter is the
    # outer sharp boundary created by removing F005 and is therefore the exact
    # boundary on which the replacement radius belongs.
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
            "Expected 8 edges around the restored rounded-rectangular loop; got %d" %
            len(replacement_edges)
        )

    print("Applying replacement radius 2.0 mm to restored F005 boundary")
    for i, edge in enumerate(replacement_edges):
        c = edge.Center()
        print("  EDGE %d type=%s length=%.6f center=(%.4f, %.4f, %.4f)" % (
            i, edge.geomType(), edge.Length(), c.x, c.y, c.z))

    # CadQuery's Solid API uses fillet(), not makeFillet(). Apply a 2 mm
    # radius to all eight connected edges so the replacement remains a single
    # continuous circumferential loop matching F006, F007, and F008.
    edited = restored_solid.fillet(2.0, replacement_edges)

    if not edited.isValid() or len(edited.Solids()) != 1:
        raise RuntimeError("Replacement radius-2 fillet did not produce one valid solid")

    print("OUTPUT VALID:", edited.isValid())
    print("OUTPUT SOLIDS:", len(edited.Solids()),
          "FACES:", len(edited.Faces()), "EDGES:", len(edited.Edges()))
    print("OUTPUT VOLUME: %.6f" % edited.Volume())

    # Report resulting curved surfaces for verification that the original
    # radius-10 surfaces are gone and the new transition is radius 2 mm.
    print("OUTPUT CURVED FACES:")
    for i, face in enumerate(edited.Faces()):
        if face.geomType() in ("CYLINDER", "TORUS"):
            c = face.Center()
            print("  FACE %d type=%s area=%.6f center=(%.4f, %.4f, %.4f)" % (
                i, face.geomType(), face.Area(), c.x, c.y, c.z))

    return cq.Workplane(obj=edited)
