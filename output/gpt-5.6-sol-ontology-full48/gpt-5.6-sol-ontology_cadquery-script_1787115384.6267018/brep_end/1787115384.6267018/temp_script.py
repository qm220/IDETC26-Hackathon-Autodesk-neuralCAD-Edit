def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    bracket_wp = cq.importers.importStep(input_file)
    bracket = bracket_wp.val() if hasattr(bracket_wp, "val") else bracket_wp

    # Inspect and bind the STEP face indices to their actual geometry before editing.
    faces = bracket.Faces()
    print(f"Loaded STEP: {input_file}")
    print(f"Bracket valid: {bracket.isValid()}, faces: {len(faces)}, solids: {len(bracket.Solids())}")
    for i, face in enumerate(faces):
        bb = face.BoundingBox()
        c = face.Center()
        try:
            gt = face.geomType()
        except Exception:
            gt = "UNKNOWN"
        print(
            f"FACE {i}: type={gt}, center=({c.x:.3f},{c.y:.3f},{c.z:.3f}), "
            f"bbox=({bb.xmin:.3f},{bb.xmax:.3f}) x "
            f"({bb.ymin:.3f},{bb.ymax:.3f}) x "
            f"({bb.zmin:.3f},{bb.zmax:.3f}), area={face.Area():.3f}"
        )

    if len(faces) < 60:
        raise ValueError("Loaded model does not contain the expected grounded STEP face topology")

    bore_faces = [faces[0], faces[1]]
    screw_centers = []
    for face_index, bore_face in zip((0, 1), bore_faces):
        bb = bore_face.BoundingBox()
        if bore_face.geomType() != "CYLINDER":
            raise ValueError(f"Grounded FACE {face_index} is not cylindrical")
        center_x = 0.5 * (bb.xmin + bb.xmax)
        center_z = 0.5 * (bb.zmin + bb.zmax)
        bore_diameter = max(bb.xmax - bb.xmin, bb.zmax - bb.zmin)
        print(
            f"Bound FACE {face_index} to mounting bore: axis center "
            f"X={center_x:.3f}, Z={center_z:.3f}, Y span=({bb.ymin:.3f},{bb.ymax:.3f}), "
            f"diameter~{bore_diameter:.3f}"
        )
        if abs(bore_diameter - 15.0) > 0.2 or abs(bb.ymin) > 0.2 or abs(bb.ymax - 15.0) > 0.2:
            raise ValueError(f"FACE {face_index} does not match the expected 15 mm through mounting bore")
        screw_centers.append((center_x, center_z))

    # Validate grounded seating and table-contact faces.
    for face_index, expected_y, label in ((57, 15.0, "upper screw-head seat"), (59, 0.0, "table-contact underside")):
        face = faces[face_index]
        bb = face.BoundingBox()
        print(f"Bound FACE {face_index} as {label}: type={face.geomType()}, Y=({bb.ymin:.3f},{bb.ymax:.3f})")
        if face.geomType() != "PLANE" or abs(bb.ymin - expected_y) > 0.2 or abs(bb.ymax - expected_y) > 0.2:
            raise ValueError(f"FACE {face_index} does not match expected reference plane Y={expected_y}")

    # Parameterized default fastener representation. The 12 mm shank gives
    # 1.5 mm diametral clearance in each existing 15 mm bore. No bracket
    # geometry, counterbore, countersink, or thread is added.
    shank_diameter = 12.0
    bore_diameter = 15.0
    head_across_flats = 18.0
    head_height = 7.5
    base_thickness = 15.0
    table_engagement = 20.0
    shank_length = base_thickness + table_engagement
    hex_corner_radius = head_across_flats / 1.7320508075688772

    print("Using simplified M12-class hex screws (threads omitted pending table insert/nut specification)")
    print(f"Shank diameter={shank_diameter:.3f}, bore diameter={bore_diameter:.3f}, diametral clearance={bore_diameter-shank_diameter:.3f}")
    print(f"Head AF={head_across_flats:.3f}, head height={head_height:.3f}, shank length={shank_length:.3f}, table engagement={table_engagement:.3f}")

    def make_screw(x, z):
        # Shank begins with a tiny overlap into the head for a robust single solid.
        shank = cq.Solid.makeCylinder(
            shank_diameter / 2.0,
            shank_length + 0.05,
            cq.Vector(x, 15.05, z),
            cq.Vector(0, -1, 0),
        )
        head_plane = cq.Plane(
            origin=cq.Vector(x, 15.0, z),
            xDir=cq.Vector(1, 0, 0),
            normal=cq.Vector(0, 1, 0),
        )
        head = (
            cq.Workplane(head_plane)
            .polygon(6, 2.0 * hex_corner_radius)
            .extrude(head_height)
            .val()
        )
        screw = head.fuse(shank)
        if not screw.isValid():
            raise ValueError("Generated screw solid is invalid")
        return screw

    screws = [make_screw(x, z) for x, z in screw_centers]
    print(f"Created {len(screws)} separate screw components at {screw_centers}")
    print("Each head underside is seated at Y=15 and each shank extends through Y=0 to Y=-20")

    # Preserve the original bracket and keep both screws removable as separate
    # assembly components rather than fusing them to SOLID 0.
    assembly = cq.Assembly(name="pedestal_bracket_with_mounting_screws")
    assembly.add(bracket, name="P001_bracket", color=cq.Color(0.55, 0.62, 0.72))
    assembly.add(screws[0], name="M12_screw_F002_FACE0", color=cq.Color(0.22, 0.22, 0.24))
    assembly.add(screws[1], name="M12_screw_F003_FACE1", color=cq.Color(0.22, 0.22, 0.24))
    return assembly