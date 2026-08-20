def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()
    solids = list(shape.Solids())
    faces = list(shape.Faces())

    print("=== INPUT GEOMETRY CHECK ===")
    print(f"valid={shape.isValid()} solids={len(solids)} faces={len(faces)} volume={shape.Volume():.6f}")
    if len(solids) != 9:
        raise ValueError(f"Expected nine solids, found {len(solids)}")

    # Confirm the grounded orientation datum FACE 466 before editing.
    datum = faces[466]
    datum_center = datum.Center()
    datum_bb = datum.BoundingBox()
    print(
        f"FACE 466: type={datum.geomType()} area={datum.Area():.6f} "
        f"center=({datum_center.x:.4f},{datum_center.y:.4f},{datum_center.z:.4f}) "
        f"bbox=({datum_bb.xmin:.3f},{datum_bb.ymin:.3f},{datum_bb.zmin:.3f})-"
        f"({datum_bb.xmax:.3f},{datum_bb.ymax:.3f},{datum_bb.zmax:.3f})"
    )
    if datum.geomType() != "PLANE" or abs(datum_center.y) > 0.01:
        raise ValueError("FACE 466 did not bind to the expected y=0 finned-housing wall")

    aqua = solids[0]
    heatsink = solids[1]

    # Geometry inspection established the corresponding mounting patterns:
    # Aqua Block (SOLID 0): x offsets +/-4.5 mm and z rows 5.5/15.5 mm.
    # Plus Heatsink (SOLID 1): existing triangular centers at
    # (35.5,20), (44.5,20), and (40,10), with axes normal to FACE 466.
    # Thus the transferred rectangular layout retains the existing top row
    # and replaces the lower center with lower corners at x=35.5/44.5.
    old_centers = [(35.5, 20.0), (44.5, 20.0), (40.0, 10.0)]
    new_centers = [(35.5, 20.0), (44.5, 20.0), (35.5, 10.0), (44.5, 10.0)]
    print(f"Existing Plus mounting centers (x,z): {old_centers}")
    print(f"Transferred four-point centers (x,z): {new_centers}")

    # Extract the exact threaded void of the existing upper-left Plus hole.
    # Its thread radii (1.2645/1.543 mm) and 0.5 mm axial segmentation match
    # the Aqua Block mounting threads found during inspection. Extracting the
    # void directly preserves the complete thread, entry transition, and blind
    # termination rather than approximating them with a plain drilled hole.
    source_center = (35.5, 20.0)
    capture_radius = 2.0
    thread_depth = 5.0
    capture = cq.Solid.makeCylinder(
        capture_radius,
        thread_depth,
        cq.Vector(source_center[0], -thread_depth, source_center[1]),
        cq.Vector(0, 1, 0)
    )
    thread_void = capture.cut(heatsink)
    print(
        f"Extracted source threaded void: valid={thread_void.isValid()} "
        f"volume={thread_void.Volume():.6f} solids={len(thread_void.Solids())}"
    )
    if thread_void.Volume() <= 0 or len(thread_void.Solids()) == 0:
        raise ValueError("Failed to extract the existing threaded mounting-hole void")

    # Remove the obsolete third mounting point by restoring its local wall
    # volume. The fill remains entirely inside the original external envelope
    # (y=-5..0) and is remote from principal bores F007/F008.
    obsolete_fill = cq.Solid.makeCylinder(
        capture_radius,
        thread_depth,
        cq.Vector(40.0, -thread_depth, 10.0),
        cq.Vector(0, 1, 0)
    )
    modified = heatsink.fuse(obsolete_fill).clean()

    # Cut two exact copies of the existing threaded mounting interface at the
    # lower Aqua-pattern corners. Existing upper mounting points are retained.
    lower_left_tool = thread_void.translate((0.0, 0.0, -10.0))
    lower_right_tool = thread_void.translate((9.0, 0.0, -10.0))
    modified = modified.cut(lower_left_tool).cut(lower_right_tool).clean()

    if not modified.isValid():
        raise ValueError("Edited finned housing is not a valid B-rep")
    if len(modified.Solids()) != 1:
        raise ValueError(f"Edited finned housing split into {len(modified.Solids())} solids")

    # Verify the resulting threaded center set from Y-axis cylindrical faces
    # adjacent to the y=0 mounting wall.
    detected = set()
    for face in modified.Faces():
        if face.geomType() != "CYLINDER":
            continue
        try:
            cyl = face._geomAdaptor().Cylinder()
            axis = cyl.Axis().Direction()
            radius = cyl.Radius()
            origin = cyl.Axis().Location()
        except Exception:
            continue
        if abs(axis.Y()) < 0.99:
            continue
        if not (1.20 <= radius <= 1.60):
            continue
        if face.BoundingBox().ymax < -1.0:
            continue
        x = round(origin.X() * 2.0) / 2.0
        z = round(origin.Z() * 2.0) / 2.0
        if 33.0 <= x <= 47.0 and 7.0 <= z <= 23.0:
            detected.add((x, z))

    print(f"Detected edited mounting centers (x,z): {sorted(detected)}")
    expected = set(new_centers)
    if not expected.issubset(detected):
        raise ValueError(f"Four-point verification failed; expected {sorted(expected)}, detected {sorted(detected)}")
    if (40.0, 10.0) in detected:
        raise ValueError("Obsolete lower-center mounting point remains after filling")

    # Preserve every other assembly component unchanged and replace only R02.
    output_solids = [solids[0], modified] + solids[2:]
    result_shape = cq.Compound.makeCompound(output_solids)
    print("=== OUTPUT GEOMETRY CHECK ===")
    print(
        f"valid={result_shape.isValid()} solids={len(result_shape.Solids())} "
        f"faces={len(result_shape.Faces())} volume={result_shape.Volume():.6f}"
    )
    print(
        "R02 rear mounting changed from triangular three-point to rectangular "
        "four-point configuration; fins, principal bores, envelope, and all "
        "other solids were preserved."
    )

    return cq.Workplane("XY").newObject([result_shape])