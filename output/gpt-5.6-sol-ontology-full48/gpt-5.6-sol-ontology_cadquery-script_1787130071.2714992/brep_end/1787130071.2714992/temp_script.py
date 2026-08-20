def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported

    print("Loaded STEP:", input_file)
    print("Valid:", root.isValid())
    print("Initial solids:", len(root.Solids()), "faces:", len(root.Faces()))

    # Inspect the planning-stage face indices against the actual imported B-rep.
    reference_face_indices = [12, 24, 25, 26, 27, 142, 154, 155, 156, 157,
                              171, 183, 184, 185, 186, 200, 212, 213, 214, 215]
    all_faces = root.Faces()
    for i in reference_face_indices:
        if i < len(all_faces):
            f = all_faces[i]
            c = f.Center()
            b = f.BoundingBox()
            try:
                kind = f.geomType()
            except Exception:
                kind = "UNKNOWN"
            print("FACE %d: type=%s center=(%.6f, %.6f, %.6f) area=%.6f bbox=(%.3f, %.3f, %.3f)" %
                  (i, kind, c.x, c.y, c.z, f.Area(), b.xlen, b.ylen, b.zlen))

    # Bind the four linkage plates to their actual STEP solids using their
    # broad XY extent, 2 mm Z thickness, and placement in the two Z layers.
    retained_solids = []
    link_solids = []
    for i, solid in enumerate(root.Solids()):
        b = solid.BoundingBox()
        c = b.center
        is_link_plate = (1.8 <= b.zlen <= 2.2 and
                         b.xlen > 75.0 and b.ylen > 35.0 and
                         20.0 < abs(c.z) < 28.0)
        print("SOLID %d: center=(%.6f, %.6f, %.6f) size=(%.6f, %.6f, %.6f) volume=%.6f link=%s" %
              (i, c.x, c.y, c.z, b.xlen, b.ylen, b.zlen,
               solid.Volume(), str(is_link_plate)))
        if is_link_plate:
            link_solids.append(solid)
        else:
            retained_solids.append(solid)

    if len(link_solids) != 4:
        raise ValueError("Expected four geometrically localized linkage plates, found %d" % len(link_solids))

    # Existing link bores are 5 mm. Interpret the requested 1 mm change as an
    # increase because the unchanged mating pins are 4.8 mm in diameter.
    d_link = 6.0
    bore_radius = d_link / 2.0

    # The original localized bosses are approximately 10 mm diameter. The new
    # continuous obround is increased by 0.5 mm per side to preserve the old
    # radial ligament after enlarging the bores: 11 mm total profile width.
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

        # Tangent parallel sides plus equal-radius terminal arcs, represented
        # robustly as a tangent rectangle fused with two endpoint cylinders.
        outline_points = [
            (x1 + nx * r, y1 + ny * r),
            (x2 + nx * r, y2 + ny * r),
            (x2 - nx * r, y2 - ny * r),
            (x1 - nx * r, y1 - ny * r)
        ]
        web = cq.Workplane("XY").polyline(outline_points).close().extrude(plate_thickness)
        cap1 = cq.Workplane("XY").center(x1, y1).circle(r).extrude(plate_thickness)
        cap2 = cq.Workplane("XY").center(x2, y2).circle(r).extrude(plate_thickness)
        plate = web.union(cap1).union(cap2)

        # Preserve both terminal axes and the original common central axis.
        centers = [p1, ((x1 + x2) / 2.0, (y1 + y2) / 2.0), p2]
        for hx, hy in centers:
            cutter = (cq.Workplane("XY")
                      .center(hx, hy)
                      .circle(bore_radius)
                      .extrude(plate_thickness + 2.0)
                      .translate((0.0, 0.0, -1.0)))
            plate = plate.cut(cutter)

        return plate.translate((0.0, 0.0, z0)).val()

    # Rebuild the four repeated links at their original separated Z positions.
    rebuilt_links = [
        make_obround_plate(upper_left, lower_right, 23.003623),
        make_obround_plate(lower_left, upper_right, 25.003623),
        make_obround_plate(upper_left, lower_right, -23.996377),
        make_obround_plate(lower_left, upper_right, -25.996377)
    ]

    for i, solid in enumerate(rebuilt_links):
        b = solid.BoundingBox()
        print("REBUILT LINK %d: center=(%.6f, %.6f, %.6f) size=(%.6f, %.6f, %.6f) volume=%.6f valid=%s" %
              (i, b.center.x, b.center.y, b.center.z, b.xlen, b.ylen, b.zlen,
               solid.Volume(), str(solid.isValid())))

    result_solids = retained_solids + rebuilt_links
    result = cq.Compound.makeCompound(result_solids)
    print("Final solids:", len(result.Solids()), "faces:", len(result.Faces()))
    print("Final valid:", result.isValid())
    print("Link bore diameter: %.3f mm; obround width: %.3f mm" %
          (d_link, 2.0 * outer_radius))
    return result