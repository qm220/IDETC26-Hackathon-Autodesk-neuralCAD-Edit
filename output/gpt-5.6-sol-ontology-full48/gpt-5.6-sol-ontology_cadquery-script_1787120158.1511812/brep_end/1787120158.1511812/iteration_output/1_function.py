def my_cad_function(args):
    import os
    import cadquery as cq
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Defeaturing

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    print("INPUT VALID:", shape.isValid())
    print("INPUT SOLIDS:", len(shape.Solids()), "FACES:", len(shape.Faces()))

    # FACE indices were bound to the imported geometry in the preceding
    # inspection run. F005, the continuous radius-10 outer transition,
    # consists of FACE 35 through FACE 42.
    source_faces = shape.Faces()
    target_indices = list(range(35, 43))
    target_faces = [source_faces[i] for i in target_indices]

    print("Removing grounded F005 faces:", target_indices)
    for i, face in zip(target_indices, target_faces):
        c = face.Center()
        print("  FACE %d type=%s area=%.6f center=(%.4f, %.4f, %.4f)" % (
            i, face.geomType(), face.Area(), c.x, c.y, c.z))

    # Remove the entire radius-10 loop and extend its neighboring faces until
    # they meet. This restores the sharp circumferential edge that existed
    # before the large fillet was applied.
    defeature = BRepAlgoAPI_Defeaturing()
    defeature.SetShape(shape.wrapped)
    for face in target_faces:
        defeature.AddFace(face.wrapped)
    defeature.Build()

    if not defeature.IsDone():
        raise RuntimeError("OCCT could not remove the continuous F005 radius-10 face loop")

    restored = cq.Shape.cast(defeature.Shape())
    if len(restored.Solids()) != 1 or not restored.isValid():
        raise RuntimeError("Defeaturing F005 did not produce one valid solid")

    print("DEFEATURED VALID:", restored.isValid(), "FACES:", len(restored.Faces()))

    # Locate the restored F004 mounting land geometrically rather than relying
    # on post-operation face numbering. Its grounded normal is approximately
    # (0, 0.965926, -0.258819), and it is an annular planar face with two wires.
    target_normal = cq.Vector(0.0, 0.9659258263, -0.2588190451)
    land_candidates = []
    for face in restored.Faces():
        if face.geomType() != "PLANE" or len(face.Wires()) < 2:
            continue
        c = face.Center()
        try:
            n = face.normalAt(c)
        except Exception:
            continue
        dot = n.dot(target_normal)
        if dot > 0.995:
            land_candidates.append((face.Area(), face, dot))

    if not land_candidates:
        raise RuntimeError("Could not locate the restored F004 annular mounting land")

    # There should be one matching annular land; area sorting makes the choice
    # deterministic if STEP healing creates an additional coplanar face.
    land_candidates.sort(key=lambda item: item[0], reverse=True)
    mounting_land = land_candidates[0][1]
    print("RESTORED LAND area=%.6f wires=%d normal_dot=%.8f" % (
        mounting_land.Area(), len(mounting_land.Wires()), land_candidates[0][2]))

    # The larger wire of this annular face is its outer boundary. These are the
    # edges shared by the restored mounting land and outer perimeter wall—the
    # exact boundary formerly occupied by F005.
    wires = mounting_land.Wires()
    wire_data = []
    for wire in wires:
        wb = wire.BoundingBox()
        span = wb.xlen + wb.ylen + wb.zlen
        wire_data.append((span, wire.Length(), wire))
        print("  LAND WIRE length=%.6f span=%.6f edges=%d" % (
            wire.Length(), span, len(wire.Edges())))

    wire_data.sort(key=lambda item: (item[0], item[1]), reverse=True)
    outer_wire = wire_data[0][2]
    replacement_edges = outer_wire.Edges()

    if len(replacement_edges) != 8:
        raise RuntimeError("Expected 8 edges in the restored rounded-rectangular outer loop, got %d" % len(replacement_edges))

    print("Applying replacement radius 2.0 mm to %d restored boundary edges" % len(replacement_edges))
    for i, edge in enumerate(replacement_edges):
        c = edge.Center()
        print("  EDGE %d type=%s length=%.6f center=(%.4f, %.4f, %.4f)" % (
            i, edge.geomType(), edge.Length(), c.x, c.y, c.z))

    # Replace the removed 10 mm transition with the same 2 mm radius used by
    # F006, F007, and F008.
    edited = restored.makeFillet(2.0, replacement_edges)

    if len(edited.Solids()) != 1 or not edited.isValid():
        raise RuntimeError("The replacement 2 mm fillet did not produce one valid solid")

    print("OUTPUT VALID:", edited.isValid())
    print("OUTPUT SOLIDS:", len(edited.Solids()), "FACES:", len(edited.Faces()), "EDGES:", len(edited.Edges()))
    print("OUTPUT VOLUME: %.6f" % edited.Volume())

    # Confirm that the former F005 region now consists of radius-2 cylindrical
    # and toroidal faces rather than radius-10 faces.
    small_transition_faces = []
    for i, face in enumerate(edited.Faces()):
        if face.geomType() not in ("CYLINDER", "TORUS"):
            continue
        fb = face.BoundingBox()
        # Replacement loop lies on the outer envelope and next to F004.
        if (abs(fb.xmin - edited.BoundingBox().xmin) < 2.1 or
                abs(fb.xmax - edited.BoundingBox().xmax) < 2.1 or
                abs(fb.ymin - edited.BoundingBox().ymin) < 2.1 or
                abs(fb.ymax - edited.BoundingBox().ymax) < 2.1 or
                abs(fb.zmin - edited.BoundingBox().zmin) < 2.1 or
                abs(fb.zmax - edited.BoundingBox().zmax) < 2.1):
            small_transition_faces.append((i, face.geomType(), face.Area()))
    print("OUTER TRANSITION CURVED FACES:", small_transition_faces)

    return cq.Workplane(obj=edited)
