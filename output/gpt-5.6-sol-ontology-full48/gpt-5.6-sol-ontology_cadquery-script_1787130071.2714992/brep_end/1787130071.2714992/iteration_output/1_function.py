def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported

    retained_solids = []
    link_solids = []
    for solid in root.Solids():
        b = solid.BoundingBox()
        c = b.center
        is_link_plate = (1.8 <= b.zlen <= 2.2 and b.xlen > 75.0 and b.ylen > 35.0 and 20.0 < abs(c.z) < 28.0)
        if is_link_plate:
            link_solids.append(solid)
        else:
            retained_solids.append(solid)

    if len(link_solids) != 4:
        raise ValueError("Expected four linkage plates, found %d" % len(link_solids))

    bore_radius = 3.0
    outer_radius = 5.5
    plate_thickness = 2.0

    lower_left = (-37.303780, 1.752975)
    lower_right = (42.743402, 1.752975)
    upper_left = (-37.303780, 44.605773)
    upper_right = (42.743402, 44.605773)

    def make_obround_plate(p1, p2, z0):
        x1, y1 = p1
        x2, y2 = p2
        dx = x2 - x1
        dy = y2 - y1
        length = (dx * dx + dy * dy) ** 0.5
        nx = -dy / length
        ny = dx / length
        r = outer_radius

        points = [(x1 + nx*r, y1 + ny*r), (x2 + nx*r, y2 + ny*r), (x2 - nx*r, y2 - ny*r), (x1 - nx*r, y1 - ny*r)]
        plate = cq.Workplane("XY").polyline(points).close().extrude(plate_thickness)
        plate = plate.union(cq.Workplane("XY").center(x1, y1).circle(r).extrude(plate_thickness))
        plate = plate.union(cq.Workplane("XY").center(x2, y2).circle(r).extrude(plate_thickness))

        centers = [p1, ((x1+x2)/2.0, (y1+y2)/2.0), p2]
        for hx, hy in centers:
            cutter = cq.Workplane("XY").center(hx, hy).circle(bore_radius).extrude(plate_thickness + 2.0).translate((0, 0, -1.0))
            plate = plate.cut(cutter)
        return plate.translate((0, 0, z0)).val()

    rebuilt_links = [
        make_obround_plate(upper_left, lower_right, 23.003623),
        make_obround_plate(lower_left, upper_right, 25.003623),
        make_obround_plate(upper_left, lower_right, -23.996377),
        make_obround_plate(lower_left, upper_right, -25.996377)
    ]

    return cq.Compound.makeCompound(retained_solids + rebuilt_links)