def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    bracket = cq.importers.importStep(input_file).val()
    bbox = bracket.BoundingBox()

    base_bottom_y = bbox.ymin
    base_top_y = base_bottom_y + 15.0
    plate_thickness = base_top_y - base_bottom_y
    thickness_mid_z = 0.5 * (bbox.zmin + bbox.zmax)

    mounting_candidates = []
    for face in bracket.Faces():
        try:
            if face.geomType() != "CYLINDER":
                continue
            fb = face.BoundingBox()
            fc = fb.center
            if not (
                fb.ymin <= base_bottom_y + 0.2
                and fb.ymax >= base_top_y - 0.2
                and fb.ylen >= plate_thickness - 0.4
                and (fc.x < bbox.xmin + 35.0 or fc.x > bbox.xmax - 35.0)
                and abs(fc.z - thickness_mid_z) < 8.0
            ):
                continue
            radius = float(face.radius())
            mounting_candidates.append((fc.x, fc.z, radius))
        except Exception:
            pass

    left_group = [c for c in mounting_candidates if c[0] < 0.5 * (bbox.xmin + bbox.xmax)]
    right_group = [c for c in mounting_candidates if c[0] >= 0.5 * (bbox.xmin + bbox.xmax)]

    if left_group and right_group:
        left = min(left_group, key=lambda c: abs(c[1] - thickness_mid_z))
        right = min(right_group, key=lambda c: abs(c[1] - thickness_mid_z))
        hole_centers = [(left[0], left[1]), (right[0], right[1])]
        hole_diameter = min(2.0 * left[2], 2.0 * right[2])
    else:
        hole_centers = [(15.0, -30.0), (153.0, -30.0)]
        hole_diameter = 15.0

    metric_sizes = [3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0]
    fitting_sizes = [d for d in metric_sizes if d <= hole_diameter - 0.35]
    nominal_diameter = fitting_sizes[-1]
    under_head_length = 40.0
    tip_length = min(2.0, 0.15 * nominal_diameter)
    head_diameter = 1.7 * nominal_diameter
    head_height = 0.65 * nominal_diameter
    head_chamfer = min(1.2, 0.09 * nominal_diameter)

    def make_socket_head_screw(cx, cz):
        down = cq.Vector(0, -1, 0)
        up = cq.Vector(0, 1, 0)
        shank_length = under_head_length - tip_length

        shank = cq.Solid.makeCylinder(
            nominal_diameter / 2.0, shank_length,
            cq.Vector(cx, base_top_y, cz), down
        )
        tip = cq.Solid.makeCone(
            nominal_diameter / 2.0, nominal_diameter * 0.38, tip_length,
            cq.Vector(cx, base_top_y - shank_length, cz), down
        )
        straight_head_height = head_height - head_chamfer
        head = cq.Solid.makeCylinder(
            head_diameter / 2.0, straight_head_height,
            cq.Vector(cx, base_top_y, cz), up
        )
        head_top = cq.Solid.makeCone(
            head_diameter / 2.0,
            head_diameter / 2.0 - head_chamfer,
            head_chamfer,
            cq.Vector(cx, base_top_y + straight_head_height, cz), up
        )
        screw = shank.fuse(tip).fuse(head).fuse(head_top)

        socket_depth = min(0.40 * nominal_diameter, 0.62 * head_height)
        socket_plane = cq.Plane(
            origin=(cx, base_top_y + head_height + 0.05, cz),
            xDir=(1, 0, 0), normal=(0, 1, 0)
        )
        socket_tool = (
            cq.Workplane(socket_plane)
            .polygon(6, 0.72 * nominal_diameter)
            .extrude(-(socket_depth + 0.10))
            .val()
        )
        return screw.cut(socket_tool)

    assembly = cq.Assembly(name="pedestal_bracket_with_two_mounting_screws")
    assembly.add(bracket, name="original_bracket", color=cq.Color(0.72, 0.72, 0.76))
    assembly.add(make_socket_head_screw(*hole_centers[0]), name="left_mounting_screw", color=cq.Color(0.22, 0.24, 0.28))
    assembly.add(make_socket_head_screw(*hole_centers[1]), name="right_mounting_screw", color=cq.Color(0.22, 0.24, 0.28))
    return assembly