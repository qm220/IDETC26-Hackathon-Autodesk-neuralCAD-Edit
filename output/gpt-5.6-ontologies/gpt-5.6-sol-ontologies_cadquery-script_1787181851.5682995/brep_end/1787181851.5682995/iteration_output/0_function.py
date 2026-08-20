def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    source_shape = imported.val() if hasattr(imported, "val") else imported

    print(f"Source valid: {source_shape.isValid()}")
    print(f"Source solids: {len(source_shape.Solids())}")
    print(f"Source volume: {source_shape.Volume():.6f}")

    faces = source_shape.Faces()
    for index, face in enumerate(faces):
        center = face.Center()
        try:
            normal = face.normalAt(center)
            normal_text = f"({normal.x:.6f}, {normal.y:.6f}, {normal.z:.6f})"
        except Exception:
            normal_text = "unavailable"
        try:
            geom_type = face.geomType()
        except Exception:
            geom_type = "unknown"
        print(
            f"FACE {index}: type={geom_type}, area={face.Area():.6f}, "
            f"center=({center.x:.6f}, {center.y:.6f}, {center.z:.6f}), "
            f"normal={normal_text}"
        )

    if len(faces) <= 7:
        raise ValueError(f"Expected FACE 7, but imported shape only has {len(faces)} faces")

    terminal_face = faces[7]
    if terminal_face.geomType() != "PLANE":
        raise ValueError(
            f"Grounded FACE 7 is not planar after import; geomType={terminal_face.geomType()}"
        )

    plane_origin = terminal_face.Center()
    plane_normal = terminal_face.normalAt(plane_origin).normalized()
    print(
        "Mirror plane from FACE 7: "
        f"origin=({plane_origin.x:.6f}, {plane_origin.y:.6f}, {plane_origin.z:.6f}), "
        f"normal=({plane_normal.x:.6f}, {plane_normal.y:.6f}, {plane_normal.z:.6f})"
    )

    mirrored_shape = source_shape.mirror(plane_normal, plane_origin)
    unified_shape = source_shape.fuse(mirrored_shape)
    try:
        unified_shape = unified_shape.clean()
    except Exception as exc:
        print(f"Topology cleanup was skipped: {exc}")

    print(f"Result valid: {unified_shape.isValid()}")
    print(f"Result solids: {len(unified_shape.Solids())}")
    print(f"Result volume: {unified_shape.Volume():.6f}")

    if len(unified_shape.Solids()) != 1:
        raise ValueError(
            f"Mirror union did not produce exactly one solid; got {len(unified_shape.Solids())}"
        )

    return cq.Workplane("XY").newObject([unified_shape])