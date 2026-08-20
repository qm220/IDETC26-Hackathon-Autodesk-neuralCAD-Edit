def my_cad_function(args):
    import os
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Vec

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    model = imported.val() if hasattr(imported, "val") else imported

    print("Loaded STEP:", input_file)
    print("Model valid:", model.isValid())
    print("Solids:", len(model.Solids()), "Faces:", len(model.Faces()))
    bbox = model.BoundingBox()
    print("Model bbox: x=(%.3f, %.3f), y=(%.3f, %.3f), z=(%.3f, %.3f)" %
          (bbox.xmin, bbox.xmax, bbox.ymin, bbox.ymax, bbox.zmin, bbox.zmax))

    faces = model.Faces()
    for i, face in enumerate(faces):
        c = face.Center()
        b = face.BoundingBox()
        try:
            n = face.normalAt(c)
            normal_text = "(%.3f, %.3f, %.3f)" % (n.x, n.y, n.z)
        except Exception:
            normal_text = "unavailable"
        print("FACE %d: area=%.6f center=(%.3f, %.3f, %.3f) bbox=[%.3f,%.3f]x[%.3f,%.3f]x[%.3f,%.3f] wires=%d normal=%s" %
              (i, face.Area(), c.x, c.y, c.z,
               b.xmin, b.xmax, b.ymin, b.ymax, b.zmin, b.zmax,
               len(face.Wires()), normal_text))

    # Bind F001/FACE 6 to the inspected geometry. The grounded receiving face
    # is the largest BSpline face, lies on the semantic +Y side, and contains
    # the wheel-pocket opening as a second boundary wire.
    candidates = []
    for i, face in enumerate(faces):
        c = face.Center()
        if len(face.Wires()) >= 2 and c.y > bbox.ymin + 0.35 * bbox.ylen:
            candidates.append((face.Area(), i, face))
    if candidates:
        candidates.sort(key=lambda item: item[0], reverse=True)
        _, receiving_index, receiving_face = candidates[0]
    else:
        receiving_index = max(range(len(faces)), key=lambda i: faces[i].Area())
        receiving_face = faces[receiving_index]
    print("Bound F001 receiving surface to actual FACE", receiving_index,
          "area=", receiving_face.Area(), "wires=", len(receiving_face.Wires()))

    # Extrude the actual curved receiving face by exactly 2 mm in semantic-top
    # direction. Intersecting this conformal 2 mm band with rounded footprint
    # prisms produces caps whose lower surfaces reproduce FACE 6.
    prism_builder = BRepPrimAPI_MakePrism(receiving_face.wrapped, gp_Vec(0.0, 2.0, 0.0), True, True)
    prism_builder.Build()
    if not prism_builder.IsDone():
        raise RuntimeError("Could not construct the 2 mm conformal FACE 6 band")
    conformal_band = cq.Shape.cast(prism_builder.Shape())

    symmetry_x = 27.0
    center_gap = 4.0
    button_width = 19.0
    button_length = 30.0
    corner_radius = 4.0
    button_center_z = 21.0
    offset_x = center_gap / 2.0 + button_width / 2.0
    button_centers_x = [symmetry_x - offset_x, symmetry_x + offset_x]

    buttons = []
    for number, center_x in enumerate(button_centers_x, start=1):
        footprint_prism = (cq.Workplane("XZ")
            .center(center_x, button_center_z)
            .rect(button_width, button_length)
            .vertices()
            .fillet2D(corner_radius)
            .extrude(100.0, both=True)
            .val())

        cap_shape = conformal_band.intersect(footprint_prism)
        cap_solids = cap_shape.Solids()
        if not cap_solids:
            raise RuntimeError("Button %d footprint did not intersect FACE 6" % number)

        # Retain the principal connected cap if the footprint merely grazes a
        # remote transition and creates a tiny sliver.
        cap = max(cap_solids, key=lambda solid: solid.Volume())
        cb = cap.BoundingBox()
        print("Button %d: center x=%.3f, solids=%d, volume=%.3f, bbox x=(%.3f,%.3f) y=(%.3f,%.3f) z=(%.3f,%.3f)" %
              (number, center_x, len(cap_solids), cap.Volume(), cb.xmin, cb.xmax,
               cb.ymin, cb.ymax, cb.zmin, cb.zmax))
        buttons.append(cap)

    if buttons[0].intersect(buttons[1]).Volume() > 1.0e-7:
        raise RuntimeError("Mirrored click-button caps intersect each other")

    # Keep the housing, wheel, and both click buttons as separate components.
    assembly = cq.Assembly(name="mouse_with_click_buttons")
    assembly.add(model, name="original_housing_and_scroll_wheel")
    assembly.add(buttons[0], name="left_click_button", color=cq.Color(0.82, 0.84, 0.88))
    assembly.add(buttons[1], name="right_click_button", color=cq.Color(0.82, 0.84, 0.88))
    print("Created two mirrored, separate, conformal click-button caps with 2.000 mm +Y height.")
    return assembly