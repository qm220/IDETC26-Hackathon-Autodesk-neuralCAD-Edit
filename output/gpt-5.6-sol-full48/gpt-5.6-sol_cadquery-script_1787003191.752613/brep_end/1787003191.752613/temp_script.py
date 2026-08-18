def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    bracket_wp = cq.importers.importStep(input_file)
    bracket = bracket_wp.val()
    bbox = bracket.BoundingBox()

    print("Bracket valid:", bracket.isValid())
    print("Bracket bbox: x=(%.3f, %.3f), y=(%.3f, %.3f), z=(%.3f, %.3f)" % (
        bbox.xmin, bbox.xmax, bbox.ymin, bbox.ymax, bbox.zmin, bbox.zmax
    ))

    base_bottom_y = bbox.ymin
    base_top_y = base_bottom_y + 15.0
    plate_thickness = base_top_y - base_bottom_y
    thickness_mid_z = 0.5 * (bbox.zmin + bbox.zmax)

    # Find only the two cylindrical through-hole walls near the longitudinal
    # ends and thickness center of the base. The z-center criterion rejects
    # the quarter-cylindrical corner rounds that were incorrectly selected in
    # the previous iteration.
    mounting_candidates = []
    for i, face in enumerate(bracket.Faces()):
        try:
            if face.geomType() != "CYLINDER":
                continue

            fb = face.BoundingBox()
            fc = fb.center
            spans_plate = (
                fb.ymin <= base_bottom_y + 0.2 and
                fb.ymax >= base_top_y - 0.2 and
                fb.ylen >= plate_thickness - 0.4
            )
            near_longitudinal_end = (
                fc.x < bbox.xmin + 35.0 or
                fc.x > bbox.xmax - 35.0
            )
            near_thickness_midplane = abs(fc.z - thickness_mid_z) < 8.0

            if not (spans_plate and near_longitudinal_end and near_thickness_midplane):
                continue

            try:
                radius = float(face.radius())
            except Exception:
                radius = 0.25 * (fb.xlen + fb.zlen)

            mounting_candidates.append({
                "index": i,
                "x": fc.x,
                "z": fc.z,
                "radius": radius,
                "area": face.Area()
            })
            print(
                "Mounting-hole candidate face %d: center=(%.3f, %.3f), diameter=%.3f, y-span=(%.3f, %.3f)" %
                (i, fc.x, fc.z, 2.0 * radius, fb.ymin, fb.ymax)
            )
        except Exception as exc:
            print("Skipped face %d during hole inspection: %s" % (i, exc))

    if len(mounting_candidates) >= 2:
        # Choose the candidate nearest each expected longitudinal end while
        # preferring its proximity to the base thickness mid-plane.
        left_group = [c for c in mounting_candidates if c["x"] < 0.5 * (bbox.xmin + bbox.xmax)]
        right_group = [c for c in mounting_candidates if c["x"] >= 0.5 * (bbox.xmin + bbox.xmax)]

        if left_group and right_group:
            left = min(left_group, key=lambda c: (abs(c["z"] - thickness_mid_z), c["x"]))
            right = min(right_group, key=lambda c: (abs(c["z"] - thickness_mid_z), -c["x"]))
        else:
            mounting_candidates.sort(key=lambda c: c["x"])
            left = mounting_candidates[0]
            right = mounting_candidates[-1]

        hole_centers = [(left["x"], left["z"]), (right["x"], right["z"])]
        measured_hole_diameter = min(2.0 * left["radius"], 2.0 * right["radius"])
    else:
        # Values established by the supplied B-rep analysis report.
        hole_centers = [(15.0, -30.0), (153.0, -30.0)]
        measured_hole_diameter = 15.0
        print("Automatic localization was inconclusive; using analyzed mounting-hole geometry.")

    # A 15 mm close-clearance hole corresponds to an M14 fastener. Select the
    # largest standard nominal diameter that remains smaller than the measured
    # cylindrical opening.
    metric_sizes = [3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0]
    fitting_sizes = [d for d in metric_sizes if d <= measured_hole_diameter - 0.35]
    nominal_diameter = fitting_sizes[-1] if fitting_sizes else max(3.0, measured_hole_diameter - 0.5)

    under_head_length = 40.0
    tip_length = min(2.0, 0.15 * nominal_diameter)
    head_diameter = 1.7 * nominal_diameter
    head_height = 0.65 * nominal_diameter
    head_chamfer = min(1.2, 0.09 * nominal_diameter)

    print("Measured mounting-hole diameter: %.3f mm" % measured_hole_diameter)
    print("Selected fastener: M%.0f x %.0f socket-head screw" % (nominal_diameter, under_head_length))
    print("Corrected screw centers:", hole_centers)

    def make_socket_head_screw(cx, cz):
        axis_down = cq.Vector(0, -1, 0)
        axis_up = cq.Vector(0, 1, 0)

        shank_length = under_head_length - tip_length
        shank = cq.Solid.makeCylinder(
            nominal_diameter / 2.0,
            shank_length,
            cq.Vector(cx, base_top_y, cz),
            axis_down
        )

        tip = cq.Solid.makeCone(
            nominal_diameter / 2.0,
            nominal_diameter * 0.38,
            tip_length,
            cq.Vector(cx, base_top_y - shank_length, cz),
            axis_down
        )

        straight_head_height = head_height - head_chamfer
        head = cq.Solid.makeCylinder(
            head_diameter / 2.0,
            straight_head_height,
            cq.Vector(cx, base_top_y, cz),
            axis_up
        )
        head_top = cq.Solid.makeCone(
            head_diameter / 2.0,
            head_diameter / 2.0 - head_chamfer,
            head_chamfer,
            cq.Vector(cx, base_top_y + straight_head_height, cz),
            axis_up
        )

        screw = shank.fuse(tip).fuse(head).fuse(head_top)

        # Hexagonal driving recess in the top face.
        socket_depth = min(0.40 * nominal_diameter, 0.62 * head_height)
        socket_circumscribed_diameter = 0.72 * nominal_diameter
        socket_plane = cq.Plane(
            origin=(cx, base_top_y + head_height + 0.05, cz),
            xDir=(1, 0, 0),
            normal=(0, 1, 0)
        )
        socket_tool = (
            cq.Workplane(socket_plane)
            .polygon(6, socket_circumscribed_diameter)
            .extrude(-(socket_depth + 0.10))
            .val()
        )
        return screw.cut(socket_tool)

    left_screw = make_socket_head_screw(*hole_centers[0])
    right_screw = make_socket_head_screw(*hole_centers[1])

    assembly = cq.Assembly(name="pedestal_bracket_with_two_mounting_screws")
    assembly.add(
        bracket,
        name="original_bracket",
        color=cq.Color(0.72, 0.72, 0.76)
    )
    assembly.add(
        left_screw,
        name="left_mounting_screw",
        color=cq.Color(0.22, 0.24, 0.28)
    )
    assembly.add(
        right_screw,
        name="right_mounting_screw",
        color=cq.Color(0.22, 0.24, 0.28)
    )

    print("Inserted two separate screws into the actual mounting holes.")
    print("Screw-head undersides are seated at y=%.3f mm." % base_top_y)
    print("Thread engagement projection below the base: %.3f mm." % (
        under_head_length - plate_thickness
    ))
    return assembly