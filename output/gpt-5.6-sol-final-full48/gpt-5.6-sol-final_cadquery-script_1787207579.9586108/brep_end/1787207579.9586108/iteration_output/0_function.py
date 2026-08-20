def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    base_shape = imported.val()
    bbox = base_shape.BoundingBox()

    # Find the largest planar X-normal face at the minimum-X end of the model.
    candidates = []
    for face in base_shape.Faces():
        try:
            if face.geomType() != "PLANE":
                continue
            center = face.Center()
            normal = face.normalAt(center)
            if abs(normal.x) < 0.95:
                continue
            if abs(center.x - bbox.xmin) > 1.0e-3:
                continue
            candidates.append((face.Area(), face))
        except Exception:
            pass

    if candidates:
        selected_face = max(candidates, key=lambda item: item[0])[1]
        face_center = selected_face.Center()
        attachment_x = face_center.x
        center_y = face_center.y
        center_z = face_center.z
        print("Selected minimum-X planar attachment face")
    else:
        # Conservative fallback based on the known principal model orientation.
        attachment_x = bbox.xmin
        center_y = (bbox.ymin + bbox.ymax) / 2.0
        center_z = (bbox.zmin + bbox.zmax) / 2.0
        print("Minimum-X planar face not found; using bounding-box center fallback")

    outer_radius = 20.0
    hole_radius = 10.0
    thickness = 30.0
    overlap = 1.0

    # Position the eye outside the minimum-X wall with a 1 mm radial overlap.
    # Its common cylinder/hole axis is along Y and therefore parallel to the
    # selected vertical X-normal surface.
    eye_center_x = attachment_x - outer_radius + overlap
    axis_start_y = center_y - thickness / 2.0

    outer = cq.Solid.makeCylinder(
        outer_radius,
        thickness,
        cq.Vector(eye_center_x, axis_start_y, center_z),
        cq.Vector(0, 1, 0)
    )

    # Fuse the outer boss first so the result is one connected solid.
    fused = base_shape.fuse(outer)

    # The cutter slightly overtravels both end faces. With the selected radial
    # overlap, its maximum X coordinate remains clear of the original body.
    cutter_extension = 1.0
    hole = cq.Solid.makeCylinder(
        hole_radius,
        thickness + 2.0 * cutter_extension,
        cq.Vector(
            eye_center_x,
            axis_start_y - cutter_extension,
            center_z
        ),
        cq.Vector(0, 1, 0)
    )
    result_shape = fused.cut(hole)

    print("Rope eye dimensions: OD=40 mm, ID=20 mm, thickness=30 mm")
    print(
        "Eye center: "
        f"({eye_center_x:.3f}, {center_y:.3f}, {center_z:.3f}) mm"
    )
    print(f"Attachment overlap: {overlap:.3f} mm")
    print(f"Result valid: {result_shape.isValid()}")
    print(f"Result solids: {len(result_shape.Solids())}")

    return cq.Workplane(obj=result_shape)
