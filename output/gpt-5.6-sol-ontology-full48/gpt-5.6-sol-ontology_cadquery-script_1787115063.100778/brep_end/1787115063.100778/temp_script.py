def my_cad_function(args):
    import os

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    bracket = imported.val() if hasattr(imported, "val") else imported

    print(f"Loaded STEP: {input_file}")
    print(f"Bracket valid: {bracket.isValid()}")
    print(f"Bracket solids: {len(bracket.Solids())}, faces: {len(bracket.Faces())}")
    bb = bracket.BoundingBox()
    print(f"Bracket bbox: x=({bb.xmin:.3f},{bb.xmax:.3f}), y=({bb.ymin:.3f},{bb.ymax:.3f}), z=({bb.zmin:.3f},{bb.zmax:.3f})")

    # Inspect and bind the planning-stage FACE indices to the imported geometry.
    faces = bracket.Faces()
    for i, face in enumerate(faces):
        fbb = face.BoundingBox()
        c = face.Center()
        try:
            gtype = face.geomType()
        except Exception:
            gtype = "UNKNOWN"
        print(
            f"FACE {i}: type={gtype}, center=({c.x:.4f},{c.y:.4f},{c.z:.4f}), "
            f"bbox=({fbb.xmin:.4f},{fbb.xmax:.4f}) x "
            f"({fbb.ymin:.4f},{fbb.ymax:.4f}) x "
            f"({fbb.zmin:.4f},{fbb.zmax:.4f}), area={face.Area():.4f}"
        )

    # Locate FACE 6 geometrically: planar top boss annulus near y=180 mm.
    boss_end_face = None
    best_score = 1.0e99
    for face in faces:
        fbb = face.BoundingBox()
        try:
            if face.geomType() != "PLANE":
                continue
        except Exception:
            continue
        dx = fbb.xmax - fbb.xmin
        dy = fbb.ymax - fbb.ymin
        dz = fbb.zmax - fbb.zmin
        score = abs(fbb.ymax - 180.0) + abs(dy) * 10.0 + abs(dx - 18.0) + abs(dz - 18.0)
        if score < best_score and dy < 0.05:
            best_score = score
            boss_end_face = face

    # Locate FACE 29 geometrically: cylindrical axial bore, approximately
    # 14.035 mm diameter and extending from y=153 to y=180 mm.
    bore_face = None
    best_bore_score = 1.0e99
    for face in faces:
        fbb = face.BoundingBox()
        try:
            if face.geomType() != "CYLINDER":
                continue
        except Exception:
            continue
        dx = fbb.xmax - fbb.xmin
        dy = fbb.ymax - fbb.ymin
        dz = fbb.zmax - fbb.zmin
        score = abs(dx - 14.035) + abs(dz - 14.035) + abs(fbb.ymin - 153.0) + abs(fbb.ymax - 180.0)
        if score < best_bore_score:
            best_bore_score = score
            bore_face = face

    if bore_face is not None:
        bbb = bore_face.BoundingBox()
        axis_x = 0.5 * (bbb.xmin + bbb.xmax)
        axis_z = 0.5 * (bbb.zmin + bbb.zmax)
        measured_bore_diameter = 0.5 * ((bbb.xmax - bbb.xmin) + (bbb.zmax - bbb.zmin))
        print(f"Bound axial bore FACE 29 candidate at x={axis_x:.4f}, z={axis_z:.4f}, diameter={measured_bore_diameter:.4f}")
    else:
        axis_x = 67.5
        axis_z = -21.0
        measured_bore_diameter = 14.035
        print("Warning: axial bore was not detected; using grounded planning coordinates.")

    if boss_end_face is not None:
        tbb = boss_end_face.BoundingBox()
        mounting_y = 0.5 * (tbb.ymin + tbb.ymax)
        print(f"Bound boss end FACE 6 candidate at y={mounting_y:.4f}")
    else:
        mounting_y = 180.0
        print("Warning: boss end annulus was not detected; using grounded y=180 mm.")

    # Sliding shank sized below the reported 14.035 mm bore diameter.
    rod_diameter = min(13.50, measured_bore_diameter - 0.40)
    rod_radius = rod_diameter / 2.0
    arm_length = 200.0

    # The lower end is directed toward the open cradle. The exact 200 mm arm
    # extends from y=45 to y=245, with 65 mm projection above FACE 6.
    lower_y = 45.0
    upper_y = lower_y + arm_length
    chamfer = 1.0
    tip_radius = rod_radius - chamfer

    # Construct an exact-overall-length rod with integral conical lead-ins.
    lower_leadin = cq.Solid.makeCone(
        tip_radius, rod_radius, chamfer,
        cq.Vector(axis_x, lower_y, axis_z), cq.Vector(0, 1, 0)
    )
    shank = cq.Solid.makeCylinder(
        rod_radius, arm_length - 2.0 * chamfer,
        cq.Vector(axis_x, lower_y + chamfer, axis_z), cq.Vector(0, 1, 0)
    )
    upper_leadin = cq.Solid.makeCone(
        rod_radius, tip_radius, chamfer,
        cq.Vector(axis_x, upper_y - chamfer, axis_z), cq.Vector(0, 1, 0)
    )
    rod = lower_leadin.fuse(shank).fuse(upper_leadin)

    # Add an integral adjustment/locking collar above the existing boss. It is
    # part of the movable rod component and does not alter the bracket.
    collar_radius = 12.0
    collar_y0 = mounting_y + 3.0
    collar_height = 8.0
    collar = cq.Solid.makeCylinder(
        collar_radius, collar_height,
        cq.Vector(axis_x, collar_y0, axis_z), cq.Vector(0, 1, 0)
    )
    rod = rod.fuse(collar)

    print(f"Rod axis: ({axis_x:.4f}, Y, {axis_z:.4f})")
    print(f"Rod shank diameter: {rod_diameter:.3f} mm")
    print(f"Rod arm endpoints: y={lower_y:.3f} to y={upper_y:.3f}; exact length={arm_length:.3f} mm")
    print(f"Projection above boss end: {upper_y - mounting_y:.3f} mm")
    print(f"Rod valid: {rod.isValid()}, rod solids: {len(rod.Solids())}")

    try:
        interference = bracket.intersect(rod)
        interference_volume = interference.Volume()
        print(f"Bracket/rod interference volume: {interference_volume:.6f} mm^3")
    except Exception as exc:
        print(f"Interference check unavailable: {exc}")

    # Preserve the original bracket and return the fixation rod as a separate,
    # adjustable assembly component rather than fusing it to SOLID 0.
    assembly = cq.Assembly(name="bracket_with_fixation_rod")
    assembly.add(bracket, name="original_bracket", color=cq.Color(0.55, 0.62, 0.70))
    assembly.add(rod, name="fixation_rod_200mm", color=cq.Color(0.85, 0.65, 0.15))
    return assembly