def my_cad_function(args):
    import os
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()
    bbox = shape.BoundingBox()

    print(f"Model valid: {shape.isValid()}")
    print(f"Solids: {len(shape.Solids())}, faces: {len(shape.Faces())}")
    print(f"Volume: {shape.Volume():.3f} mm^3")
    print(
        "Bounding box: "
        f"X=[{bbox.xmin:.3f}, {bbox.xmax:.3f}], "
        f"Y=[{bbox.ymin:.3f}, {bbox.ymax:.3f}], "
        f"Z=[{bbox.zmin:.3f}, {bbox.zmax:.3f}]"
    )
    print(
        f"Bounding-box center: ({bbox.center.x:.3f}, "
        f"{bbox.center.y:.3f}, {bbox.center.z:.3f})"
    )

    # Report large planar/cylindrical faces near the semantic top-right
    # (+Y/-Z) and bottom-left (-Y/+Z) regions for the next iteration.
    face_data = []
    for index, face in enumerate(shape.Faces()):
        fb = face.BoundingBox()
        center = face.Center()
        area = face.Area()
        if area > 100.0:
            face_data.append((area, index, center.x, center.y, center.z,
                              fb.xlen, fb.ylen, fb.zlen, face.geomType()))

    face_data.sort(reverse=True)
    print("Largest 30 faces: area, index, center, extents, type")
    for item in face_data[:30]:
        print(item)

    print("Candidate peripheral faces near +Y/-Z or -Y/+Z:")
    y_span = max(bbox.ylen, 1.0)
    z_span = max(bbox.zlen, 1.0)
    for item in face_data:
        area, index, x, y, z, dx, dy, dz, geom = item
        top_right = y > bbox.ymin + 0.70*y_span and z < bbox.zmin + 0.30*z_span
        bottom_left = y < bbox.ymin + 0.30*y_span and z > bbox.zmin + 0.70*z_span
        if top_right or bottom_left:
            print(item)

    return model