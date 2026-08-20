def my_cad_function(args):
    import os
    import math

    input_file = os.path.expanduser(args["input_file"])
    bracket_wp = cq.importers.importStep(input_file)
    bracket = bracket_wp.val()

    hole_faces = []
    for face in bracket.Faces():
        try:
            if face.geomType() != "CYLINDER":
                continue
            bb = face.BoundingBox()
            c = face.Center()
            if (bb.ymin < 0.1 and bb.ymax > 14.9 and
                    14.5 < bb.xlen < 15.5 and
                    14.5 < bb.zlen < 15.5 and
                    650.0 < face.Area() < 760.0):
                hole_faces.append((c.x, c.z))
        except Exception:
            pass

    hole_centers = []
    for x, z in hole_faces:
        if not any(abs(x - px) < 0.1 and abs(z - pz) < 0.1
                   for px, pz in hole_centers):
            hole_centers.append((x, z))
    hole_centers.sort(key=lambda p: p[0])

    if len(hole_centers) != 2:
        raise ValueError(
            "Unable to identify exactly two 15 mm base mounting holes; "
            "found centers: %s" % hole_centers
        )

    shank_radius = 6.8
    under_head_length = 35.0
    head_radius = 10.5
    head_height = 14.0
    top_chamfer_height = 2.0
    tip_chamfer_height = 1.5
    base_top_y = 15.0

    def make_mounting_screw(cx, cz):
        straight_shank = cq.Solid.makeCylinder(
            shank_radius,
            under_head_length - tip_chamfer_height,
            cq.Vector(cx, base_top_y, cz),
            cq.Vector(0, -1, 0)
        )
        tip = cq.Solid.makeCone(
            shank_radius,
            shank_radius - 1.0,
            tip_chamfer_height,
            cq.Vector(cx, base_top_y - under_head_length + tip_chamfer_height, cz),
            cq.Vector(0, -1, 0)
        )
        head_body = cq.Solid.makeCylinder(
            head_radius,
            head_height - top_chamfer_height,
            cq.Vector(cx, base_top_y, cz),
            cq.Vector(0, 1, 0)
        )
        head_top = cq.Solid.makeCone(
            head_radius,
            head_radius - 1.0,
            top_chamfer_height,
            cq.Vector(cx, base_top_y + head_height - top_chamfer_height, cz),
            cq.Vector(0, 1, 0)
        )

        screw = straight_shank.fuse(tip).fuse(head_body).fuse(head_top)

        socket_plane = cq.Plane(
            origin=(cx, base_top_y + head_height + 0.1, cz),
            xDir=(1, 0, 0),
            normal=(0, -1, 0)
        )
        socket_circum_diameter = 10.0 / math.cos(math.radians(30.0))
        socket_cut = (
            cq.Workplane(socket_plane)
            .polygon(6, socket_circum_diameter)
            .extrude(7.1)
            .val()
        )
        return screw.cut(socket_cut)

    left_screw = make_mounting_screw(*hole_centers[0])
    right_screw = make_mounting_screw(*hole_centers[1])

    result = cq.Assembly(name="table_mounting_assembly")
    result.add(bracket, name="clamp_bracket", color=cq.Color(0.72, 0.71, 0.66))
    result.add(left_screw, name="left_M14_mounting_screw", color=cq.Color(0.25, 0.27, 0.30))
    result.add(right_screw, name="right_M14_mounting_screw", color=cq.Color(0.25, 0.27, 0.30))

    print("Located base-hole centers:", hole_centers)
    print("Inserted two separate simplified M14 socket-head mounting screws.")
    return result