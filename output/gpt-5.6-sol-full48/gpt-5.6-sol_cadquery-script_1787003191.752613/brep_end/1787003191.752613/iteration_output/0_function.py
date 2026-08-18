def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    bracket_wp = cq.importers.importStep(input_file)
    bracket = bracket_wp.val()

    bbox = bracket.BoundingBox()
    print("Bracket valid:", bracket.isValid())
    print("Bracket bbox: x=(%.3f, %.3f), y=(%.3f, %.3f), z=(%.3f, %.3f)" % (
        bbox.xmin, bbox.xmax, bbox.ymin, bbox.ymax, bbox.zmin, bbox.zmax
    ))
    print("Bracket faces:", len(bracket.Faces()))

    # Find cylindrical faces passing through the 15 mm base plate near its ends.
    hole_candidates = []
    for i, face in enumerate(bracket.Faces()):
        try:
            if face.geomType() != "CYLINDER":
                continue
            fb = face.BoundingBox()
            fc = fb.center
            spans_base = fb.ymin <= bbox.ymin + 0.2 and fb.ymax >= bbox.ymin + 14.8
            near_end = fc.x < bbox.xmin + 35.0 or fc.x > bbox.xmax - 35.0
            approximately_vertical = fb.ylen > 14.0 and fb.xlen < 30.0 and fb.zlen < 30.0
            if spans_base and near_end and approximately_vertical:
                try:
                    radius = float(face.radius())
                except Exception:
                    radius = 0.25 * (fb.xlen + fb.zlen)
                hole_candidates.append((fc.x, fc.z, radius, i, fb))
                print("Base-hole candidate face %d: center=(%.3f, %.3f), diameter=%.3f, y-span=(%.3f, %.3f)" % (
                    i, fc.x, fc.z, 2.0 * radius, fb.ymin, fb.ymax
                ))
        except Exception:
            pass

    # Select one candidate at each longitudinal end. Fall back to the dimensions
    # identified by the supplied B-rep analysis if topology ordering differs.
    if len(hole_candidates) >= 2:
        hole_candidates.sort(key=lambda item: item[0])
        left = hole_candidates[0]
        right = hole_candidates[-1]
        hole_centers = [(left[0], left[1]), (right[0], right[1])]
        measured_hole_diameter = min(2.0 * left[2], 2.0 * right[2])
    else:
        hole_centers = [(15.0, -30.0), (153.0, -30.0)]
        measured_hole_diameter = 11.0
        print("Automatic hole localization was inconclusive; using analyzed mounting-hole centers.")

    # Pick the largest common metric screw whose nominal major diameter has
    # clearance in the measured plain through hole.
    metric_sizes = [3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0]
    fitting_sizes = [d for d in metric_sizes if d <= measured_hole_diameter - 0.35]
    nominal_diameter = fitting_sizes[-1] if fitting_sizes else max(3.0, measured_hole_diameter - 0.5)

    base_top_y = bbox.ymin + 15.0
    plate_thickness = 15.0
    under_head_length = 40.0
    head_diameter = 1.7 * nominal_diameter
    head_height = 0.65 * nominal_diameter
    edge_chamfer = min(1.0, 0.12 * nominal_diameter)
    tip_length = min(2.0, 0.20 * nominal_diameter)

    print("Measured mounting-hole diameter: %.3f mm" % measured_hole_diameter)
    print("Selected screw size: M%.1f, under-head length %.1f mm" % (
        nominal_diameter, under_head_length
    ))
    print("Screw centers:", hole_centers)

    def make_socket_head_screw(cx, cz):
        axis_down = cq.Vector(0, -1, 0)
        axis_up = cq.Vector(0, 1, 0)

        # Full-diameter shank passes through the plate and projects below the
        # mounting datum for engagement with a table thread or T-slot nut.
        shank = cq.Solid.makeCylinder(
            nominal_diameter / 2.0,
            under_head_length - tip_length,
            cq.Vector(cx, base_top_y, cz),
            axis_down
        )
        tip_start_y = base_top_y - (under_head_length - tip_length)
        tip = cq.Solid.makeCone(
            nominal_diameter / 2.0,
            nominal_diameter * 0.36,
            tip_length,
            cq.Vector(cx, tip_start_y, cz),
            axis_down
        )

        # Cylindrical socket-head cap screw. The underside is exactly seated on
        # the existing base upper deck, without modifying the bracket holes.
        head_body_height = head_height - edge_chamfer
        head = cq.Solid.makeCylinder(
            head_diameter / 2.0,
            head_body_height,
            cq.Vector(cx, base_top_y, cz),
            axis_up
        )
        head_top = cq.Solid.makeCone(
            head_diameter / 2.0,
            head_diameter / 2.0 - edge_chamfer,
            edge_chamfer,
            cq.Vector(cx, base_top_y + head_body_height, cz),
            axis_up
        )

        screw = shank.fuse(tip).fuse(head).fuse(head_top)

        # Recess a hexagonal driving socket into the top of the head.
        socket_depth = min(0.40 * nominal_diameter, 0.65 * head_height)
        socket_diameter = 0.72 * nominal_diameter
        top_y = base_top_y + head_height
        socket_plane = cq.Plane(
            origin=(cx, top_y + 0.05, cz),
            xDir=(1, 0, 0),
            normal=(0, 1, 0)
        )
        socket_tool = (
            cq.Workplane(socket_plane)
            .polygon(6, socket_diameter)
            .extrude(-(socket_depth + 0.10))
            .val()
        )
        screw = screw.cut(socket_tool)
        return screw

    screws = [make_socket_head_screw(cx, cz) for cx, cz in hole_centers]

    assembly = cq.Assembly(name="pedestal_bracket_with_mounting_screws")
    assembly.add(bracket, name="original_bracket", color=cq.Color(0.72, 0.72, 0.76))
    assembly.add(screws[0], name="left_mounting_screw", color=cq.Color(0.22, 0.24, 0.28))
    assembly.add(screws[1], name="right_mounting_screw", color=cq.Color(0.22, 0.24, 0.28))

    print("Inserted two separate screw components; original bracket geometry is unchanged.")
    print("Projection below base underside: %.3f mm" % (under_head_length - plate_thickness))
    return assembly