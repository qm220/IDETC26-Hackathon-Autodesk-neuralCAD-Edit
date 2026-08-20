def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    imported_shape = imported.val() if hasattr(imported, "val") else imported
    solids = imported_shape.Solids()
    if not solids:
        raise ValueError("The input STEP file contains no solids")

    original = solids[0]
    faces = original.Faces()
    print("Input valid:", original.isValid())
    print("Input solids:", len(solids), "faces:", len(faces))

    for i, face in enumerate(faces):
        center = face.Center()
        try:
            normal = face.normalAt()
            normal_text = "({:.4f}, {:.4f}, {:.4f})".format(normal.x, normal.y, normal.z)
        except Exception:
            normal_text = "n/a"
        print("FACE {}: type={} area={:.6f} center=({:.4f}, {:.4f}, {:.4f}) normal={}".format(
            i, face.geomType(), face.Area(), center.x, center.y, center.z, normal_text
        ))

    def is_annular_plane(face):
        try:
            return face.geomType() == "PLANE" and len(face.Wires()) >= 2
        except Exception:
            return False

    # Bind the analyzed STEP topology. FACE 12 is the broad land opposite the
    # large 10 mm radius treatment, so it is the requested bottom side.
    bottom_face = faces[12] if len(faces) > 12 else None
    top_face = faces[34] if len(faces) > 34 else None

    if bottom_face is None or not is_annular_plane(bottom_face):
        annular_planes = [face for face in faces if is_annular_plane(face)]
        if not annular_planes:
            raise ValueError("Could not locate the planar annular bottom land")
        bottom_face = max(annular_planes, key=lambda face: face.Area())
        print("FACE 12 fallback selected area:", bottom_face.Area())

    if top_face is None or top_face.geomType() != "PLANE":
        annular_planes = [face for face in faces if is_annular_plane(face)]
        alternatives = [face for face in annular_planes if face is not bottom_face]
        if not alternatives:
            raise ValueError("Could not locate the opposite top land")
        top_face = min(alternatives, key=lambda face: face.Area())

    print("Bound bottom land: area={:.6f}, wires={}".format(
        bottom_face.Area(), len(bottom_face.Wires())
    ))
    print("Bound opposite/top land: area={:.6f}".format(top_face.Area()))
    if len(faces) > 42:
        print("Large-radius top references FACE 35..42:", [
            (i, faces[i].geomType(), round(faces[i].Area(), 3))
            for i in range(35, 43)
        ])

    base_center = bottom_face.Center()
    base_normal = bottom_face.normalAt().normalized()
    body_center = original.Center()

    # Extrude away from the body so the new terminal face is the bottom.
    toward_body = body_center.sub(base_center)
    away = base_normal.multiply(-1.0) if base_normal.dot(toward_body) > 0 else base_normal
    top_displacement = top_face.Center().sub(base_center).dot(away)
    print("Bottom support direction: ({:.6f}, {:.6f}, {:.6f})".format(
        away.x, away.y, away.z
    ))
    print("Opposite land displacement along bottom direction:", top_displacement)
    if top_displacement >= 0:
        raise ValueError("Resolved support direction does not point away from the large-radius top")

    outer_wire = bottom_face.outerWire()
    inner_wires = bottom_face.innerWires()
    if len(inner_wires) != 1:
        raise ValueError("Expected exactly one central opening in the bottom land")
    original_inner = inner_wires[0]
    original_opening_face = cq.Face.makeFromWires(original_inner, [])
    original_opening_area = original_opening_face.Area()

    # Offset the opening contour 20 mm into the opening. CadQuery's signed
    # offset depends on wire orientation, so test both signs and retain the
    # valid contour having a smaller enclosed area.
    candidates = []
    for distance in (20.0, -20.0):
        try:
            generated = original_inner.offset2D(distance, kind="arc")
            generated_wires = generated if isinstance(generated, (list, tuple)) else [generated]
            for wire in generated_wires:
                try:
                    candidate_face = cq.Face.makeFromWires(wire, [])
                    area = candidate_face.Area()
                    if candidate_face.isValid() and area < original_opening_area - 1.0:
                        candidates.append((area, distance, wire))
                        print("Offset candidate sign={} area={:.6f}".format(distance, area))
                except Exception as candidate_error:
                    print("Rejected offset result for sign {}: {}".format(distance, candidate_error))
        except Exception as offset_error:
            print("Offset attempt {} failed: {}".format(distance, offset_error))

    if not candidates:
        raise ValueError("Could not create a valid 20 mm inward offset of the opening")

    # Prefer the largest reduced opening, avoiding any incidental small loops.
    candidates.sort(key=lambda item: item[0], reverse=True)
    reduced_area, chosen_sign, reduced_inner = candidates[0]
    print("Selected offset sign={}; opening area {:.6f} -> {:.6f}".format(
        chosen_sign, original_opening_area, reduced_area
    ))

    # Extrude the entire bottom footprint by 5 mm while using the reduced
    # opening. This thickens the existing bottom footprint and adds a continuous
    # 20 mm inward step around the central opening.
    support = cq.Solid.extrudeLinear(
        outer_wire,
        [reduced_inner],
        away.multiply(5.0)
    )
    if not support.isValid():
        raise ValueError("The unfilleted 5 mm support extrusion is invalid")

    # Select only the reduced opening loop on the upper support plane. The
    # corresponding lower loop is deliberately excluded so its bottom edge
    # remains sharp. Filleting this upper loop produces the requested smooth
    # 2 mm transition when viewed or approached from above.
    reference_edges = reduced_inner.Edges()
    reference_centers = [edge.Center() for edge in reference_edges]
    upper_transition_edges = []

    for edge in support.Edges():
        edge_center = edge.Center()
        plane_distance = abs(edge_center.sub(base_center).dot(base_normal))
        if plane_distance > 1.0e-4:
            continue
        nearest_distance = min(
            edge_center.sub(reference_center).Length
            for reference_center in reference_centers
        )
        if nearest_distance < 1.0e-3:
            upper_transition_edges.append(edge)

    print("Offset contour edges:", len(reference_edges))
    print("Selected upper transition edges:", len(upper_transition_edges))
    if len(upper_transition_edges) != len(reference_edges):
        raise ValueError("Could not identify the complete upper transition loop")

    support_rounded = support.fillet(2.0, upper_transition_edges)
    if not support_rounded.isValid():
        raise ValueError("The support is invalid after applying the 2 mm upper fillet")

    result = original.fuse(support_rounded).clean()
    result_solids = result.Solids()
    print("Final valid:", result.isValid())
    print("Final solids:", len(result_solids), "faces:", len(result.Faces()))
    print("Final volume: {:.6f} mm^3".format(result.Volume()))

    if not result.isValid() or len(result_solids) != 1:
        raise ValueError("The edited frame is not one valid solid")

    # Verify that the terminal bottom remains planar and exactly 5 mm below the
    # original bottom land. No edge on this plane was included in the fillet.
    terminal_faces = []
    for face in result.Faces():
        if face.geomType() != "PLANE":
            continue
        distance = face.Center().sub(base_center).dot(away)
        if abs(distance - 5.0) < 1.0e-3:
            terminal_faces.append(face)

    terminal_area = sum(face.Area() for face in terminal_faces)
    print("Planar terminal bottom faces at 5 mm:", len(terminal_faces))
    print("Total terminal bottom area: {:.6f}".format(terminal_area))
    if not terminal_faces or terminal_area <= bottom_face.Area():
        raise ValueError("A flat enlarged terminal bottom was not produced")

    return cq.Workplane("XY").newObject([result])