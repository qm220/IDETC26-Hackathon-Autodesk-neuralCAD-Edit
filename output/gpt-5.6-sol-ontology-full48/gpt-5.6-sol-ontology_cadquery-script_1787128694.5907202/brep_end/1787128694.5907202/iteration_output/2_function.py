def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()
    solids = list(shape.Solids())
    faces = list(shape.Faces())

    datum = faces[466]
    if datum.geomType() != "PLANE" or abs(datum.Center().y) > 0.01:
        raise ValueError("FACE 466 did not bind to the expected y=0 finned-housing wall")
    if len(solids) != 9:
        raise ValueError(f"Expected nine solids, found {len(solids)}")

    heatsink = solids[1]
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
    if thread_void.Volume() <= 0 or len(thread_void.Solids()) == 0:
        raise ValueError("Failed to extract the existing threaded mounting-hole void")

    obsolete_fill = cq.Solid.makeCylinder(
        capture_radius,
        thread_depth,
        cq.Vector(40.0, -thread_depth, 10.0),
        cq.Vector(0, 1, 0)
    )
    modified = heatsink.fuse(obsolete_fill).clean()

    lower_left_tool = thread_void.translate((0.0, 0.0, -10.0))
    lower_right_tool = thread_void.translate((9.0, 0.0, -10.0))
    modified = modified.cut(lower_left_tool).cut(lower_right_tool).clean()

    if not modified.isValid() or len(modified.Solids()) != 1:
        raise ValueError("Edited finned housing is not a valid single solid")

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
        if abs(axis.Y()) < 0.99 or not (1.20 <= radius <= 1.60):
            continue
        if face.BoundingBox().ymax < -1.0:
            continue
        center = (round(origin.X() * 2.0) / 2.0, round(origin.Z() * 2.0) / 2.0)
        if 33.0 <= center[0] <= 47.0 and 7.0 <= center[1] <= 23.0:
            detected.add(center)

    expected = {(35.5, 20.0), (44.5, 20.0), (35.5, 10.0), (44.5, 10.0)}
    if not expected.issubset(detected) or (40.0, 10.0) in detected:
        raise ValueError(f"Four-point verification failed: {sorted(detected)}")

    result_shape = cq.Compound.makeCompound([solids[0], modified] + solids[2:])
    return cq.Workplane("XY").newObject([result_shape])