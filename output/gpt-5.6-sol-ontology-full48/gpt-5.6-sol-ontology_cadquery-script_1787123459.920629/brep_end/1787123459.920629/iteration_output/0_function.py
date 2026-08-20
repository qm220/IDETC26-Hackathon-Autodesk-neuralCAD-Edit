def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    model = imported.val() if hasattr(imported, "val") else imported

    solids = list(model.Solids())
    faces = list(model.Faces())
    print("Loaded STEP:", input_file)
    print("Valid:", model.isValid(), "solids:", len(solids), "faces:", len(faces))

    # Bind the grounded STEP indices to the actual imported geometry.
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

    # Inspect the control-region solids to verify the imported solid ordering.
    for solid_index in range(37, min(48, len(solids))):
        solid = solids[solid_index]
        bb = solid.BoundingBox()
        center = solid.Center()
        print(
            "SOLID %d: volume=%.6f center=(%.4f, %.4f, %.4f) "
            "size=(%.4f, %.4f, %.4f) bbox=(%.4f, %.4f, %.4f)-(%.4f, %.4f, %.4f)"
            % (
                solid_index, solid.Volume(), center.x, center.y, center.z,
                bb.xlen, bb.ylen, bb.zlen,
                bb.xmin, bb.ymin, bb.zmin,
                bb.xmax, bb.ymax, bb.zmax,
            )
        )

    if len(solids) <= 39:
        raise ValueError("Expected F013 source geometry at SOLID 39, but the STEP contains fewer solids")

    # F013 is the complete existing horizontal button body. Copying the solid
    # preserves its rounded ends, depth, mounting offset, and all blends.
    source_button = solids[39]
    source_bb = source_button.BoundingBox()

    # Use one shared center-to-center pitch for the symmetric three-button row.
    # The source is a shallow horizontal feature; 25 mm gives visible, nearly
    # uniform spacing while retaining clearance within the control-panel area.
    pitch = 25.0
    upper_button = source_button.moved(cq.Location(cq.Vector(0, 0, pitch)))
    lower_button = source_button.moved(cq.Location(cq.Vector(0, 0, -pitch)))

    print(
        "Copied SOLID 39 at translations (0,0,+%.3f) and (0,0,-%.3f); "
        "source bbox size=(%.4f, %.4f, %.4f)"
        % (pitch, pitch, source_bb.xlen, source_bb.ylen, source_bb.zlen)
    )

    # Preserve every original assembly body and append the two new disconnected
    # button bodies, matching the assembly structure of the existing button.
    result = cq.Compound.makeCompound([model, upper_button, lower_button])
    print("Result valid:", result.isValid(), "result solids:", len(result.Solids()))
    return result