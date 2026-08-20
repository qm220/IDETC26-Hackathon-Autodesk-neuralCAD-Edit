def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    model = imported.val() if hasattr(imported, "val") else imported

    solids = list(model.Solids())
    faces = list(model.Faces())
    print("Loaded STEP:", input_file)
    print("Valid:", model.isValid(), "solids:", len(solids), "faces:", len(faces))

    # Bind the analyzed front-panel and existing-button geometry to the STEP.
    for face_index in (58, 424):
        if face_index < len(faces):
            face = faces[face_index]
            center = face.Center()
            bb = face.BoundingBox()
            try:
                geom_type = face.geomType()
            except Exception:
                geom_type = "unknown"
            print(
                "FACE %d: type=%s area=%.6f center=(%.4f, %.4f, %.4f) "
                "bbox=(%.4f, %.4f, %.4f)-(%.4f, %.4f, %.4f)"
                % (
                    face_index, geom_type, face.Area(),
                    center.x, center.y, center.z,
                    bb.xmin, bb.ymin, bb.zmin,
                    bb.xmax, bb.ymax, bb.zmax,
                )
            )

    if len(solids) <= 39:
        raise ValueError("Expected existing horizontal button at SOLID 39")

    # Confirm SOLID 39 is the shallow, X-elongated horizontal button associated
    # with grounded FACE 424 rather than relying on its index without inspection.
    source_button = solids[39]
    source_bb = source_button.BoundingBox()
    source_center = source_button.Center()
    print(
        "SOLID 39 source button: volume=%.6f center=(%.4f, %.4f, %.4f) "
        "size=(%.4f, %.4f, %.4f) bbox=(%.4f, %.4f, %.4f)-(%.4f, %.4f, %.4f)"
        % (
            source_button.Volume(),
            source_center.x, source_center.y, source_center.z,
            source_bb.xlen, source_bb.ylen, source_bb.zlen,
            source_bb.xmin, source_bb.ymin, source_bb.zmin,
            source_bb.xmax, source_bb.ymax, source_bb.zmax,
        )
    )

    if not (source_bb.xlen > source_bb.ylen and source_bb.xlen > source_bb.zlen):
        raise ValueError("SOLID 39 does not have the expected horizontal-button proportions")

    # In the front-panel (+Z) view, X is horizontal and Y is the visual
    # above/below direction. Preserve Z so both copies remain seated on the same
    # panel surface. A common 25 mm center pitch creates an equally spaced stack.
    pitch = 25.0
    upper_button = source_button.moved(cq.Location(cq.Vector(0, pitch, 0)))
    lower_button = source_button.moved(cq.Location(cq.Vector(0, -pitch, 0)))

    print(
        "Copied SOLID 39 along front-panel Y direction at translations "
        "(0,+%.3f,0) and (0,-%.3f,0)" % (pitch, pitch)
    )
    print(
        "Button centers: lower=(%.4f, %.4f, %.4f), existing=(%.4f, %.4f, %.4f), "
        "upper=(%.4f, %.4f, %.4f)"
        % (
            source_center.x, source_center.y - pitch, source_center.z,
            source_center.x, source_center.y, source_center.z,
            source_center.x, source_center.y + pitch, source_center.z,
        )
    )

    # Preserve the complete original assembly and append two exact copies as
    # separate button solids, consistent with the original assembly structure.
    result = cq.Compound.makeCompound([model, upper_button, lower_button])
    print("Result valid:", result.isValid(), "result solids:", len(result.Solids()))
    return result