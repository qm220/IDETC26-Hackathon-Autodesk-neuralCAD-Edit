def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    model_shape = imported.val() if hasattr(imported, "val") else imported

    faces = model_shape.Faces()
    print(f"Loaded STEP: {input_file}")
    print(f"Valid: {model_shape.isValid()}")
    print(f"Original solids: {len(model_shape.Solids())}")
    print(f"Original faces: {len(faces)}")

    # Inspect and bind the planning-stage FACE N identifiers to actual STEP faces.
    for index, face in enumerate(faces):
        center = face.Center()
        try:
            normal = face.normalAt()
            normal_text = f"({normal.x:.6f}, {normal.y:.6f}, {normal.z:.6f})"
        except Exception:
            normal_text = "n/a"
        try:
            geom_type = face.geomType()
        except Exception:
            geom_type = "unknown"
        print(
            f"FACE {index}: type={geom_type}, "
            f"center=({center.x:.6f}, {center.y:.6f}, {center.z:.6f}), "
            f"normal={normal_text}, area={face.Area():.6f}"
        )

    if len(faces) <= 72:
        raise ValueError(f"Expected at least 73 faces, but loaded model has {len(faces)}")

    # Grounded references from OP01: front FACE 53 and opposed rear FACE 72.
    front_face = faces[53]
    rear_face = faces[72]
    thickness_mm = 0.254 * 10.0

    def make_outward_cover(reference_face, label):
        if reference_face.geomType() != "PLANE":
            raise ValueError(f"{label} reference is not planar: {reference_face.geomType()}")

        center = reference_face.Center()
        normal = reference_face.normalAt().normalized()
        vector = normal.multiply(thickness_mm)
        outer_wire = reference_face.outerWire()

        print(
            f"Creating {label}: flush origin=({center.x:.6f}, {center.y:.6f}, {center.z:.6f}), "
            f"outward normal=({normal.x:.6f}, {normal.y:.6f}, {normal.z:.6f}), "
            f"thickness={thickness_mm:.6f} mm"
        )

        # Extruding the grounded outer boundary outward leaves the inner cover face
        # exactly coincident with the corresponding original hub outer face.
        cover = cq.Solid.extrudeLinear(outer_wire, [], vector)
        if not cover.isValid():
            raise ValueError(f"Generated {label} is invalid")
        return cover

    front_cover = make_outward_cover(front_face, "front_cover_FACE_53")
    rear_cover = make_outward_cover(rear_face, "rear_cover_FACE_72")

    print(f"Front cover volume: {front_cover.Volume():.6f} mm^3")
    print(f"Rear cover volume: {rear_cover.Volume():.6f} mm^3")
    print("Created exactly two separate contour-matched cover solids; original geometry is unchanged.")

    result = cq.Assembly(name="crossed_arm_hub_with_covers")
    result.add(model_shape, name="original_model")
    result.add(front_cover, name="front_cover")
    result.add(rear_cover, name="rear_cover")
    return result