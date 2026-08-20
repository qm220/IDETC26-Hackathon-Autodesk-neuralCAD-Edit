def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    loaded_shape = imported.val()

    solids = loaded_shape.Solids()
    if not solids:
        raise ValueError("The input STEP file contains no solids")
    base = solids[0]

    print(f"Input valid: {base.isValid()}")
    print(f"Input solids: {len(solids)}")
    print(f"Input faces: {len(base.Faces())}")
    base_bb = base.BoundingBox()
    print(f"Input bbox: x=({base_bb.xmin:.6f},{base_bb.xmax:.6f}), y=({base_bb.ymin:.6f},{base_bb.ymax:.6f}), z=({base_bb.zmin:.6f},{base_bb.zmax:.6f})")

    faces = base.Faces()
    for index, face in enumerate(faces):
        bb = face.BoundingBox()
        center = face.Center()
        try:
            geometry_type = face.geomType()
        except Exception:
            geometry_type = "UNKNOWN"
        print(
            f"FACE {index}: type={geometry_type}, area={face.Area():.6f}, "
            f"center=({center.x:.6f},{center.y:.6f},{center.z:.6f}), "
            f"bbox=x({bb.xmin:.6f},{bb.xmax:.6f}) "
            f"y({bb.ymin:.6f},{bb.ymax:.6f}) "
            f"z({bb.zmin:.6f},{bb.zmax:.6f})"
        )

    # Bind planned FACE 32 to the actual imported geometry. Fall back to a
    # geometric search for the planar x-min terminal wall if face ordering
    # differs from the STEP analysis.
    target_face = None
    target_index = None
    if len(faces) > 32:
        candidate = faces[32]
        bb = candidate.BoundingBox()
        try:
            is_expected = (
                candidate.geomType() == "PLANE"
                and abs(bb.xmax - bb.xmin) < 1.0e-5
                and abs(0.5 * (bb.xmin + bb.xmax) - base_bb.xmin) < 1.0e-4
            )
        except Exception:
            is_expected = False
        if is_expected:
            target_face = candidate
            target_index = 32

    if target_face is None:
        best_score = None
        for index, face in enumerate(faces):
            bb = face.BoundingBox()
            try:
                planar = face.geomType() == "PLANE"
            except Exception:
                planar = False
            if not planar or abs(bb.xmax - bb.xmin) >= 1.0e-5:
                continue
            plane_x = 0.5 * (bb.xmin + bb.xmax)
            if abs(plane_x - base_bb.xmin) > 1.0e-3:
                continue
            y_span = bb.ymax - bb.ymin
            z_span = bb.zmax - bb.zmin
            score = abs(y_span - 60.0) + abs(z_span - 80.0)
            if best_score is None or score < best_score:
                best_score = score
                target_face = face
                target_index = index

    if target_face is None:
        raise ValueError("Could not locate the planar rear terminal wall corresponding to FACE 32")

    target_bb = target_face.BoundingBox()
    surface_x = 0.5 * (target_bb.xmin + target_bb.xmax)
    center_y = 0.5 * (target_bb.ymin + target_bb.ymax)
    center_z = 0.5 * (target_bb.zmin + target_bb.zmax)
    print(f"Bound target FACE {target_index} at x={surface_x:.6f}")
    print(f"Target bounds: y=({target_bb.ymin:.6f},{target_bb.ymax:.6f}), z=({target_bb.zmin:.6f},{target_bb.zmax:.6f})")
    print(f"Attachment reference center: ({surface_x:.6f},{center_y:.6f},{center_z:.6f})")

    outer_radius = 20.0
    hole_radius = 10.0
    thickness = 30.0
    overlap = 0.5

    # Axis is parallel to the target x=constant face and aligned with CAD Y.
    # A 0.5 mm penetration replaces mathematically exact tangency so the edit
    # produces one robust, manufacturable solid.
    eye_center_x = surface_x - outer_radius + overlap
    start_y = center_y - thickness / 2.0
    axis = cq.Vector(0.0, 1.0, 0.0)
    cylinder_origin = cq.Vector(eye_center_x, start_y, center_z)

    outer_cylinder = cq.Solid.makeCylinder(
        outer_radius, thickness, cylinder_origin, axis
    )
    hole_cylinder = cq.Solid.makeCylinder(
        hole_radius, thickness, cylinder_origin, axis
    )
    annular_eye = outer_cylinder.cut(hole_cylinder)

    if not annular_eye.isValid():
        raise ValueError("The generated annular rope eye is invalid")

    result_shape = base.fuse(annular_eye)
    if not result_shape.isValid():
        raise ValueError("The fused edited model is invalid")

    result_solids = result_shape.Solids()
    print(f"Eye center: ({eye_center_x:.6f},{center_y:.6f},{center_z:.6f})")
    print(f"Eye outer diameter: {2.0 * outer_radius:.6f} mm")
    print(f"Eye hole diameter: {2.0 * hole_radius:.6f} mm")
    print(f"Eye thickness: {thickness:.6f} mm, y=({start_y:.6f},{start_y + thickness:.6f})")
    print(f"Radial annular wall: {outer_radius - hole_radius:.6f} mm")
    print(f"Attachment penetration: {overlap:.6f} mm")
    print(f"Result valid: {result_shape.isValid()}")
    print(f"Result solids: {len(result_solids)}")
    print(f"Result faces: {len(result_shape.Faces())}")

    if len(result_solids) != 1:
        raise ValueError(f"Expected one fused solid, obtained {len(result_solids)}")

    return cq.Workplane(obj=result_shape)