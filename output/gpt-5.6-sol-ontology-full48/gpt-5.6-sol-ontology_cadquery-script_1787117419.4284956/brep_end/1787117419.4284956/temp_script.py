def my_cad_function(args):
    import os
    import cadquery as cq
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
        center = face.Center()
        fb = face.BoundingBox()
        try:
            normal = face.normalAt(center)
            normal_text = "(%.3f, %.3f, %.3f)" % (normal.x, normal.y, normal.z)
        except Exception:
            normal_text = "unavailable"
        print("FACE %d: area=%.6f center=(%.3f, %.3f, %.3f) bbox=[%.3f,%.3f]x[%.3f,%.3f]x[%.3f,%.3f] wires=%d normal=%s" %
              (i, face.Area(), center.x, center.y, center.z,
               fb.xmin, fb.xmax, fb.ymin, fb.ymax, fb.zmin, fb.zmax,
               len(face.Wires()), normal_text))

    # Bind F001 to the inspected upper BSpline face. FACE 6 is distinguished
    # by its large area, semantic-top location, and two boundary wires (the
    # second wire surrounds the wheel-clearance opening).
    receiving_candidates = []
    for i, face in enumerate(faces):
        center = face.Center()
        if len(face.Wires()) >= 2 and center.y > bbox.ymin + 0.5 * bbox.ylen:
            receiving_candidates.append((face.Area(), i, face))

    if not receiving_candidates:
        raise RuntimeError("Could not bind F001/FACE 6 from the loaded STEP geometry")

    receiving_candidates.sort(key=lambda item: item[0], reverse=True)
    _, receiving_index, receiving_face = receiving_candidates[0]
    print("Bound F001 receiving surface to actual FACE", receiving_index,
          "area=", receiving_face.Area(), "wires=", len(receiving_face.Wires()))

    # Sweep the actual receiving face 2 mm toward semantic top (+Y). Clipping
    # this conformal band by each footprint leaves the original curved FACE 6
    # as the lower button surface and a corresponding surface 2 mm above it.
    height = 2.0
    prism_builder = BRepPrimAPI_MakePrism(
        receiving_face.wrapped, gp_Vec(0.0, height, 0.0), True, True
    )
    prism_builder.Build()
    if not prism_builder.IsDone():
        raise RuntimeError("Could not construct the 2 mm conformal upper-face band")
    conformal_band = cq.Shape.cast(prism_builder.Shape())

    symmetry_x = 27.0
    center_gap = 4.0
    button_width = 19.0
    button_length = 30.0
    button_center_z = 21.0
    x_offset = center_gap / 2.0 + button_width / 2.0
    button_centers = [symmetry_x - x_offset, symmetry_x + x_offset]

    buttons = []
    for number, center_x in enumerate(button_centers, start=1):
        # Elliptical caps give a smooth, comfortable footprint and avoid the
        # unavailable Workplane.fillet2D method from the previous iteration.
        footprint_prism = (
            cq.Workplane("XZ")
            .center(center_x, button_center_z)
            .ellipse(button_width / 2.0, button_length / 2.0)
            .extrude(100.0, both=True)
            .val()
        )

        clipped = conformal_band.intersect(footprint_prism)
        cap_solids = clipped.Solids()
        if not cap_solids:
            raise RuntimeError("Button %d footprint did not intersect F001/FACE 6" % number)

        cap = max(cap_solids, key=lambda solid: solid.Volume())
        cb = cap.BoundingBox()
        print("Button %d: center=(%.3f, %.3f), volume=%.3f, bbox x=(%.3f,%.3f) y=(%.3f,%.3f) z=(%.3f,%.3f)" %
              (number, center_x, button_center_z, cap.Volume(),
               cb.xmin, cb.xmax, cb.ymin, cb.ymax, cb.zmin, cb.zmax))

        # The pocket starts around z=43.5. Both frontward button footprints
        # must terminate before that boundary and remain on their own side of
        # the wheel region.
        if cb.zmax >= 43.4:
            raise RuntimeError("Button %d intrudes into the wheel-pocket region" % number)
        buttons.append(cap)

    overlap = buttons[0].intersect(buttons[1])
    if overlap.Solids() and overlap.Volume() > 1.0e-7:
        raise RuntimeError("The two mirrored click-button caps intersect")

    # Preserve the housing, scroll wheel, and button caps as separate movable
    # components rather than fusing the caps into the housing.
    result = cq.Assembly(name="mouse_with_click_buttons")
    result.add(model, name="original_mouse")
    result.add(buttons[0], name="left_click_button",
               color=cq.Color(0.82, 0.84, 0.88))
    result.add(buttons[1], name="right_click_button",
               color=cq.Color(0.82, 0.84, 0.88))

    print("Created two separate mirrored click-button caps, each 2.000 mm high in semantic-top direction.")
    return result
