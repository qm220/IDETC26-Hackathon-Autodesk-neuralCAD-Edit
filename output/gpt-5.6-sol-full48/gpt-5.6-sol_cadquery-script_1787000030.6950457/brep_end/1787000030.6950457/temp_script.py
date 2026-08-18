def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    original = model.val()

    bbox = original.BoundingBox()
    x_mid = bbox.center.x
    rib_thickness = 1.5
    lower_clearance = 0.55

    # Determine the underside cavity cross-section automatically on the
    # transverse YZ plane. Y is the bracket height and Z is transverse;
    # the previous revision incorrectly treated Z as the height axis.
    y_min, y_max = bbox.ymin, bbox.ymax
    z_min, z_max = bbox.zmin, bbox.zmax
    lower_y = y_min + lower_clearance

    def point_inside(x, y, z):
        try:
            return original.isInside(cq.Vector(x, y, z), 1.0e-5)
        except TypeError:
            return original.isInside(cq.Vector(x, y, z))

    # Sample just outside the rib center plane where necessary so an
    # existing longitudinal rib does not conceal the cavity roof.
    probe_x_values = [
        x_mid - 0.45 * rib_thickness,
        x_mid + 0.45 * rib_thickness,
        x_mid
    ]
    z_step = max(0.045, bbox.zlen / 180.0)
    y_step = max(0.035, bbox.ylen / 150.0)
    z_count = int(round((z_max - z_min) / z_step)) + 1
    y_count = int(round((y_max - y_min) / y_step)) + 1

    roof_samples = []
    for iz in range(z_count):
        z = z_min + (z_max - z_min) * iz / max(1, z_count - 1)
        probe_entries = []

        for px in probe_x_values:
            states = []
            ys = []
            for iy in range(y_count):
                y = y_min + (y_max - y_min) * iy / max(1, y_count - 1)
                ys.append(y)
                states.append(point_inside(px, y, z))

            # Find all solid runs and use the highest run. Its lower edge is
            # the cavity roof even when a lower longitudinal rib is present.
            runs = []
            run_start = None
            for i, state in enumerate(states):
                if state and run_start is None:
                    run_start = i
                if run_start is not None and ((not state) or i == len(states) - 1):
                    run_end = i if state and i == len(states) - 1 else i - 1
                    if run_end >= run_start:
                        runs.append((run_start, run_end))
                    run_start = None

            if runs:
                highest_run = max(runs, key=lambda r: r[1])
                probe_entries.append(ys[highest_run[0]])

        if probe_entries:
            # Taking the largest entry avoids mistaking a low existing rib
            # for the upper supporting shell.
            roof_y = max(probe_entries)
            if roof_y > lower_y + 0.35:
                roof_samples.append((z, roof_y))
            else:
                roof_samples.append(None)
        else:
            roof_samples.append(None)

    # Divide valid samples into contiguous cavity intervals and select the
    # widest interval beneath the central clevis.
    intervals = []
    current = []
    for sample in roof_samples:
        if sample is not None:
            current.append(sample)
        elif current:
            intervals.append(current)
            current = []
    if current:
        intervals.append(current)

    intervals = [seg for seg in intervals if len(seg) >= 5]
    if not intervals:
        raise ValueError("Could not identify a usable underside cavity interval")

    cavity = max(intervals, key=lambda seg: seg[-1][0] - seg[0][0])

    # Trim one sample from each end to keep the web inside the cavity wall
    # envelope. The roof overlap provides a reliable structural union.
    if len(cavity) > 8:
        cavity = cavity[1:-1]

    z0 = cavity[0][0]
    z1 = cavity[-1][0]
    roof_overlap = 0.10

    # Reduce the number of roof vertices while retaining its local contour.
    stride = max(1, len(cavity) // 28)
    contour = cavity[::stride]
    if contour[-1] != cavity[-1]:
        contour.append(cavity[-1])

    profile_points = [(lower_y, z0), (lower_y, z1)]
    for z, roof_y in reversed(contour):
        profile_points.append((min(roof_y + roof_overlap, y_max), z))

    rib_wp = cq.Workplane("YZ", origin=(x_mid, 0.0, 0.0))
    rib_wp = rib_wp.moveTo(profile_points[0][0], profile_points[0][1])
    for y, z in profile_points[1:]:
        rib_wp = rib_wp.lineTo(y, z)
    rib = rib_wp.close().extrude(rib_thickness / 2.0, both=True)

    result_shape = original.fuse(rib.val()).clean()

    if not result_shape.isValid():
        raise ValueError("Bracket became invalid after adding the cavity rib")

    solids = result_shape.Solids()
    if len(solids) != 1:
        raise ValueError(
            "The transverse rib did not merge into the bracket; solid count: %d"
            % len(solids)
        )

    result_bbox = result_shape.BoundingBox()
    added_volume = result_shape.Volume() - original.Volume()
    if added_volume <= 0.01:
        raise ValueError("The transverse rib added no meaningful material")

    tol = 1.0e-4
    if result_bbox.ymin < bbox.ymin - tol:
        raise ValueError("The rib projects below the original bottom datum")
    if result_bbox.zmin < bbox.zmin - tol or result_bbox.zmax > bbox.zmax + tol:
        raise ValueError("The rib projects beyond the original transverse envelope")

    print("RIB OPERATION: transverse underside reinforcing rib")
    print("RIB THICKNESS: %.3f mm, symmetric about X=%.5f" % (rib_thickness, x_mid))
    print("HEIGHT AXIS: Y; TRANSVERSE AXIS: Z")
    print("RIB CAVITY SPAN Z: %.5f to %.5f" % (z0, z1))
    print("RIB LOWER Y: %.5f (%.3f mm above datum)" % (lower_y, lower_clearance))
    print("ORIGINAL BBOX X/Y/Z: %.5f x %.5f x %.5f" % (bbox.xlen, bbox.ylen, bbox.zlen))
    print("ORIGINAL VOLUME: %.6f" % original.Volume())
    print("RESULT VOLUME: %.6f" % result_shape.Volume())
    print("ADDED NET VOLUME: %.6f" % added_volume)
    print("RESULT VALID:", result_shape.isValid())
    print("RESULT SOLIDS:", len(solids))
    print("RESULT FACES:", len(result_shape.Faces()))

    return cq.Workplane("XY").newObject([result_shape])