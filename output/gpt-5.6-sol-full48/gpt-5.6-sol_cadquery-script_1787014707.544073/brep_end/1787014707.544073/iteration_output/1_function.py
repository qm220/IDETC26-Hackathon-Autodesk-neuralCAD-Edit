def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    bbox = shape.BoundingBox()
    print(f"Input valid: {shape.isValid()}")
    print(f"Input volume: {shape.Volume():.3f} mm^3")
    print(f"Bounding box: X[{bbox.xmin:.3f}, {bbox.xmax:.3f}] Y[{bbox.ymin:.3f}, {bbox.ymax:.3f}] Z[{bbox.zmin:.3f}, {bbox.zmax:.3f}]")
    print(f"Faces: {len(shape.Faces())}")

    candidates = []
    for index, face in enumerate(shape.Faces()):
        try:
            if face.geomType() != "PLANE":
                continue
            center = face.Center()
            normal = face.normalAt()
            if abs(normal.x) > 0.90:
                area = face.Area()
                candidates.append((center.x, -area, index, face, center, normal))
                print(
                    f"X-normal planar face {index}: center=({center.x:.3f}, "
                    f"{center.y:.3f}, {center.z:.3f}), area={area:.3f}, "
                    f"normal=({normal.x:.3f}, {normal.y:.3f}, {normal.z:.3f})"
                )
        except Exception as exc:
            print(f"Skipped face {index}: {exc}")

    if candidates:
        candidates.sort(key=lambda item: (item[0], item[1]))
        _, _, face_index, rear_face, face_center, face_normal = candidates[0]
        rear_x = face_center.x
        center_y = face_center.y
        center_z = face_center.z
        print(f"Selected rear terminal face index: {face_index}")
    else:
        rear_x = bbox.xmin
        center_y = (bbox.ymin + bbox.ymax) * 0.5
        center_z = (bbox.zmin + bbox.zmax) * 0.5
        print("No suitable planar face found; using minimum-X bounding-box datum")

    outer_radius = 20.0
    inner_radius = 10.0
    thickness = 30.0
    penetration = 0.20
    eye_center_x = rear_x - outer_radius + penetration

    eye_plane = cq.Plane(
        origin=(eye_center_x, center_y, center_z),
        xDir=(1.0, 0.0, 0.0),
        normal=(0.0, 1.0, 0.0)
    )
    eye = (
        cq.Workplane(eye_plane)
        .circle(outer_radius)
        .circle(inner_radius)
        .extrude(thickness * 0.5, both=True)
    )

    result = model.union(eye).clean()
    result_shape = result.val()
    result_bbox = result_shape.BoundingBox()

    print(f"Rope eye center: ({eye_center_x:.3f}, {center_y:.3f}, {center_z:.3f}) mm")
    print("Rope eye dimensions: OD=40 mm, hole=20 mm, thickness=30 mm")
    print(f"Nominal rear-face penetration: {penetration:.3f} mm")
    print(f"Result valid: {result_shape.isValid()}")
    print(f"Result solids: {len(result_shape.Solids())}")
    print(f"Result volume: {result_shape.Volume():.3f} mm^3")
    print(
        f"Result bounding box: X[{result_bbox.xmin:.3f}, {result_bbox.xmax:.3f}] "
        f"Y[{result_bbox.ymin:.3f}, {result_bbox.ymax:.3f}] "
        f"Z[{result_bbox.zmin:.3f}, {result_bbox.zmax:.3f}]"
    )

    return result