def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    base = imported.val() if hasattr(imported, "val") else imported

    print(f"Loaded STEP: {input_file}")
    print(f"Valid: {base.isValid()}, solids: {len(base.Solids())}, faces: {len(base.Faces())}")
    model_bb = base.BoundingBox()
    print(
        f"Model bounds: x=({model_bb.xmin:.3f},{model_bb.xmax:.3f}), "
        f"y=({model_bb.ymin:.3f},{model_bb.ymax:.3f}), "
        f"z=({model_bb.zmin:.3f},{model_bb.zmax:.3f})"
    )

    # Inspect the imported topology and bind the unfilleted flat terminal face
    # geometrically rather than relying solely on the planning-stage face index.
    terminal_candidates = []
    for index, face in enumerate(base.Faces()):
        fbb = face.BoundingBox()
        center = face.Center()
        geom = face.geomType()
        try:
            normal = face.normalAt(center)
            normal_text = f"({normal.x:.3f},{normal.y:.3f},{normal.z:.3f})"
        except Exception:
            normal_text = "unavailable"

        print(
            f"FACE {index}: {geom}, area={face.Area():.6f}, "
            f"center=({center.x:.3f},{center.y:.3f},{center.z:.3f}), "
            f"bounds=({fbb.xmin:.3f},{fbb.xmax:.3f})/"
            f"({fbb.ymin:.3f},{fbb.ymax:.3f})/"
            f"({fbb.zmin:.3f},{fbb.zmax:.3f}), normal={normal_text}"
        )

        is_constant_x = abs(fbb.xmax - fbb.xmin) < 1.0e-5
        is_at_max_x = abs(fbb.xmax - model_bb.xmax) < 1.0e-4
        if geom == "PLANE" and is_constant_x and is_at_max_x:
            terminal_candidates.append((face.Area(), face))

    if not terminal_candidates:
        raise ValueError("Could not locate the unfilleted planar terminal face at maximum X")

    terminal_face = max(terminal_candidates, key=lambda item: item[0])[1]
    terminal_bb = terminal_face.BoundingBox()
    terminal_center = terminal_face.Center()

    axis_x = terminal_bb.xmax
    axis_y = terminal_center.y
    axis_z = terminal_center.z
    axis_start = cq.Vector(axis_x, axis_y, axis_z)
    axis_end = cq.Vector(axis_x + 1.0, axis_y, axis_z)
    axis_direction = cq.Vector(1.0, 0.0, 0.0)

    print(
        f"Bound unfilleted terminal face at x={axis_x:.6f}; "
        f"bearing axis=({axis_y:.6f},{axis_z:.6f}) parallel to +X"
    )

    # Cylindrical roller-bearing parameters. The bearing housing is mounted on
    # the selected flat end. One cylindrical roller is designed first and seven
    # exact duplicates are circularly rotated about the bearing's X axis.
    outer_radius = float(args.get("bearing_outer_radius", 8.0))
    outer_race_inner_radius = float(args.get("outer_race_inner_radius", 6.5))
    inner_race_outer_radius = float(args.get("inner_race_outer_radius", 4.5))
    shaft_bore_radius = float(args.get("shaft_bore_radius", 2.5))
    roller_pitch_radius = float(args.get("roller_pitch_radius", 5.5))
    roller_radius = float(args.get("roller_radius", 0.9))
    bearing_length = float(args.get("bearing_length", 8.0))
    roller_count = 8

    if not (
        outer_radius > outer_race_inner_radius
        and outer_race_inner_radius > roller_pitch_radius + roller_radius
        and roller_pitch_radius - roller_radius > inner_race_outer_radius
        and inner_race_outer_radius > shaft_bore_radius > 0
        and bearing_length > 0
    ):
        raise ValueError("Bearing dimensions do not provide valid race and roller clearances")

    # Slight overlap at the terminal end provides a robust integral mounting
    # flange while leaving the working bearing open and recognizable.
    race_start_x = axis_x
    race_start = cq.Vector(race_start_x, axis_y, axis_z)

    outer_race_outer = cq.Solid.makeCylinder(
        outer_radius, bearing_length, race_start, axis_direction
    )
    outer_race_void = cq.Solid.makeCylinder(
        outer_race_inner_radius, bearing_length, race_start, axis_direction
    )
    outer_race = outer_race_outer.cut(outer_race_void)

    inner_race_outer = cq.Solid.makeCylinder(
        inner_race_outer_radius, bearing_length, race_start, axis_direction
    )
    shaft_bore = cq.Solid.makeCylinder(
        shaft_bore_radius, bearing_length, race_start, axis_direction
    )
    inner_race = inner_race_outer.cut(shaft_bore)

    # A short annular mounting flange overlaps the original terminal by 0.5 mm,
    # joining the bearing assembly to the existing part without altering the
    # opposite rounded/filleted socket end.
    flange_start = cq.Vector(axis_x - 0.5, axis_y, axis_z)
    flange_outer = cq.Solid.makeCylinder(
        outer_radius, 1.0, flange_start, axis_direction
    )
    flange_bore = cq.Solid.makeCylinder(
        shaft_bore_radius, 1.0, flange_start, axis_direction
    )
    mounting_flange = flange_outer.cut(flange_bore)

    mounted_body = base.fuse(mounting_flange).fuse(outer_race).fuse(inner_race).clean()

    # Create the first cylindrical roller at +Z on the pitch circle.
    roller_start_x = axis_x + 0.6
    roller_length = bearing_length - 1.0
    first_roller_start = cq.Vector(
        roller_start_x,
        axis_y,
        axis_z + roller_pitch_radius
    )
    first_roller = cq.Solid.makeCylinder(
        roller_radius, roller_length, first_roller_start, axis_direction
    )

    rollers = []
    angle_step = 360.0 / roller_count
    for occurrence in range(roller_count):
        angle = occurrence * angle_step
        if occurrence == 0:
            roller = first_roller
            print("Created original cylindrical roller instance 1/8 at 0.000 degrees")
        else:
            # Rotate an exact duplicate of the first roller around the resolved
            # bearing axis; this creates seven additional visible instances.
            roller = first_roller.rotate(axis_start, axis_end, angle)
            print(
                f"Created duplicate cylindrical roller instance {occurrence + 1}/8 "
                f"at {angle:.3f} degrees"
            )
        rollers.append(roller)

    # Rollers are intentionally separate bearing components contained between
    # the races. Preserve them as distinct solids in a single exported compound.
    result = cq.Compound.makeCompound([mounted_body] + rollers)

    print(
        f"Created cylindrical roller bearing: OD={2.0 * outer_radius:.3f} mm, "
        f"shaft bore={2.0 * shaft_bore_radius:.3f} mm, "
        f"length={bearing_length:.3f} mm"
    )
    print(
        f"Circular pattern: 1 original + 7 additional roller instances, "
        f"spacing={angle_step:.3f} degrees about the bearing X-axis"
    )
    print(
        f"Result valid: {result.isValid()}, solids: {len(result.Solids())}, "
        f"volume={result.Volume():.6f} mm^3"
    )
    return cq.Workplane(obj=result)