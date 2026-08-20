def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    source_shape = imported.val() if hasattr(imported, "val") else imported

    faces = source_shape.Faces()
    if len(faces) <= 7:
        raise ValueError(f"Expected FACE 7, but imported shape only has {len(faces)} faces")

    terminal_face = faces[7]
    if terminal_face.geomType() != "PLANE":
        raise ValueError(
            f"Grounded FACE 7 is not planar after import; geomType={terminal_face.geomType()}"
        )

    plane_origin = terminal_face.Center()
    plane_normal = terminal_face.normalAt(plane_origin).normalized()

    mirrored_shape = source_shape.mirror(plane_normal, plane_origin)
    unified_shape = source_shape.fuse(mirrored_shape)
    try:
        unified_shape = unified_shape.clean()
    except Exception:
        pass

    if not unified_shape.isValid():
        raise ValueError("The resulting mirrored and fused shape is invalid")
    if len(unified_shape.Solids()) != 1:
        raise ValueError(
            f"Mirror union did not produce exactly one solid; got {len(unified_shape.Solids())}"
        )

    return cq.Workplane("XY").newObject([unified_shape])