def my_cad_function(args):
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
        c = face.Center()
        try:
            n = face.normalAt()
            normal_text = "({:.4f}, {:.4f}, {:.4f})".format(n.x, n.y, n.z)
        except Exception:
            normal_text = "n/a"
        print("FACE {}: type={} area={:.6f} center=({:.4f}, {:.4f}, {:.4f}) normal={}".format(
            i, face.geomType(), face.Area(), c.x, c.y, c.z, normal_text
        ))

    # Bind the planned B-rep references to the imported topology. FACE 12 is
    # expected to be the broad bottom land, while FACE 34 is the narrow land
    # adjacent to the large-radius top edge treatment.
    bottom_face = faces[12] if len(faces) > 12 else None
    top_face = faces[34] if len(faces) > 34 else None

    def is_annular_plane(face):
        try:
            return face.geomType() == "PLANE" and len(face.Wires()) >= 2
        except Exception:
            return False

    if bottom_face is None or not is_annular_plane(bottom_face):
        annular_planes = [f for f in faces if is_annular_plane(f)]
        if not annular_planes:
            raise ValueError("Could not locate a planar annular frame land")
        bottom_face = max(annular_planes, key=lambda f: f.Area())
        print("FACE 12 fallback: selected annular plane with area", bottom_face.Area())

    if top_face is None or top_face.geomType() != "PLANE":
        planar_faces = [f for f in faces if f.geomType() == "PLANE"]
        top_face = min(planar_faces, key=lambda f: f.Area())

    print("Bound bottom land: area={:.6f}, wires={}".format(
        bottom_face.Area(), len(bottom_face.Wires())
    ))
    print("Bound opposite/top land: area={:.6f}".format(top_face.Area()))
    if len(faces) > 42:
        print("Large-radius top references FACE 35..42:",
              [(i, faces[i].geomType(), round(faces[i].Area(), 3)) for i in range(35, 43)])

    base_center = bottom_face.Center()
    base_normal = bottom_face.normalAt().normalized()

    # Choose the extrusion direction that points away from the existing body.
    # This makes FACE 12 the upper face of the new 5 mm bottom support.
    body_center = original.Center()
    toward_body = body_center.sub(base_center)
    if base_normal.dot(toward_body) > 0:
        away = base_normal.multiply(-1.0)
    else:
        away = base_normal

    top_direction = top_face.Center().sub(base_center)
    print("Bottom support extrusion direction: ({:.6f}, {:.6f}, {:.6f})".format(
        away.x, away.y, away.z
    ))
    print("FACE 34 direction from FACE 12 dot extrusion direction:",
          top_direction.dot(away))

    outer_wire = bottom_face.outerWire()
    inner_wires = bottom_face.innerWires()
    if len(inner_wires) != 1:
        raise ValueError("Expected FACE 12 to contain one central opening")
    original_inner = inner_wires[0]
    original_inner_area = cq.Face.makeFromWires(original_inner).Area()

    # Offset the opening contour by 20 mm into the opening. Try both signed
    # offsets and retain the continuous result whose enclosed area is smaller.
    offset_candidates = []
    for distance in (20.0, -20.0):
        try:
            generated = original_inner.offset2D(distance, kind="arc")
            for wire in generated:
                if not wire.isClosed():
                    continue
                candidate_face = cq.Face.makeFromWires(wire)
                area = candidate_face.Area()
                if candidate_face.isValid() and area < original_inner_area - 1.0:
                    offset_candidates.append((abs((original_inner_area - area)), area, distance, wire))
                    print("Inner offset candidate: distance={} area={:.6f}".format(distance, area))
        except Exception as exc:
            print("Offset attempt {} failed: {}".format(distance, exc))

    if not offset_candidates:
        raise ValueError("Could not create the 20 mm inward offset of the opening")

    # There should be one erosion result. The largest valid reduced opening is
    # preferred in case OCC returns incidental small loops.
    offset_candidates.sort(key=lambda item: item[1], reverse=True)
    _, reduced_area, chosen_sign, reduced_inner = offset_candidates[0]
    print("Selected 20 mm offset sign={}, original opening area={:.6f}, reduced area={:.6f}".format(
        chosen_sign, original_inner_area, reduced_area
    ))

    extrusion = away.multiply(5.0)
    support = cq.Solid.extrudeLinear(outer_wire, [reduced_inner], extrusion)
    if not support.isValid():
        raise ValueError("The unfilleted support extrusion is invalid")

    # Locate only the upper inner loop of the new support. These edges lie in
    # the FACE 12 plane and geometrically coincide with the reduced opening
    # wire. Lower edges at the terminal bottom plane are deliberately excluded.
    reduced_edges = reduced_inner.Edges()
    reduced_centers = [edge.Center() for edge in reduced_edges]
    upper_inner_edges = []
    for edge in support.Edges():
        ec = edge.Center()
        plane_distance = abs(ec.sub(base_center).dot(base_normal))
        if plane_distance > 1.0e-4:
            continue
        nearest = min(ec.sub(rc).Length for rc in reduced_centers)
        if nearest < 1.0e-3:
            upper_inner_edges.append(edge)

    print("Reduced opening segments:", len(reduced_edges),
          "selected upper transition edges:", len(upper_inner_edges))
    if len(upper_inner_edges) != len(reduced_edges):
        raise ValueError("Failed to identify the complete upper inner transition loop")

    # Apply the requested 2 mm radius only from above. Since this is done before
    # fusion, no terminal bottom edge can accidentally enter the selection.
    support_rounded = support.fillet(2.0, upper_inner_edges)
    if not support_rounded.isValid():
        raise ValueError("The support became invalid after applying the 2 mm top fillet")

    result = original.fuse(support_rounded).clean()
    result_solids = result.Solids()
    print("Final valid:", result.isValid())
    print("Final solids:", len(result_solids), "faces:", len(result.Faces()))
    print("Final volume: {:.6f} mm^3".format(result.Volume()))

    if not result.isValid() or len(result_solids) != 1:
        raise ValueError("The edited frame is not one valid solid")

    # Verify terminal bottom faces remain planar and occur exactly 5 mm from
    # FACE 12. No fillet was applied to their incident edges.
    terminal_faces = []
    for face in result.Faces():
        if face.geomType() != "PLANE":
            continue
        signed_distance = face.Center().sub(base_center).dot(away)
        if abs(signed_distance - 5.0) < 1.0e-3:
            terminal_faces.append(face)
    print("Planar terminal bottom faces at 5 mm:", len(terminal_faces),
          "total area={:.6f}".format(sum(f.Area() for f in terminal_faces)))
    if not terminal_faces:
        raise ValueError("No flat terminal bottom face was found at the required 5 mm depth")

    return cq.Workplane("XY").newObject([result])