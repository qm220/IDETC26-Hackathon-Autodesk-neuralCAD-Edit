def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    base_shape = model.val()

    # Inspect and bind the planned FACE indices to the imported STEP geometry.
    print("Loaded STEP:", input_file)
    print("Valid:", base_shape.isValid(), "Faces:", len(base_shape.Faces()), "Volume:", base_shape.Volume())
    for index, face in enumerate(base_shape.Faces()):
        bb = face.BoundingBox()
        c = face.Center()
        try:
            geometry_type = face.geomType()
        except Exception:
            geometry_type = "UNKNOWN"
        print(
            "FACE %d type=%s area=%.6f center=(%.3f,%.3f,%.3f) "
            "bbox=(%.3f,%.3f,%.3f)-(%.3f,%.3f,%.3f)" % (
                index, geometry_type, face.Area(), c.x, c.y, c.z,
                bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax
            )
        )

    # Editable pattern and support parameters from operation.json.
    centers_x = [0.0, 24.0, 48.0, 72.0]
    boss_radius = 7.0
    socket_radius = 5.0
    boss_start_y = 24.0
    opening_y = 34.0
    socket_bottom_y = 25.0
    axis_z = 4.0
    rib_thickness = 2.0
    rib_base_half_length = 5.0
    rib_base_y = 18.5
    rib_tip_y = 27.0
    rib_fillet = 0.8

    result = model

    # Add three complete outer boss/root instances. The existing x=0 instance
    # remains the seed. Each new boss has a Y-axis cylindrical portion and a
    # tapered elliptical root that overlaps the lever web.
    for xc in centers_x[1:]:
        boss_plane = cq.Plane(
            origin=(xc, boss_start_y, axis_z),
            xDir=(1, 0, 0),
            normal=(0, 1, 0)
        )
        boss = cq.Workplane(boss_plane).circle(boss_radius).extrude(opening_y - boss_start_y)

        root_plane = cq.Plane(
            origin=(xc, boss_start_y, axis_z),
            xDir=(1, 0, 0),
            normal=(0, -1, 0)
        )
        root = (
            cq.Workplane(root_plane)
            .circle(boss_radius)
            .workplane(offset=5.0)
            .ellipse(9.0, 3.0)
            .loft(combine=True)
        )

        result = result.union(boss).union(root)

    # Add balanced integral gusset ribs on the two broad arm sides. Ribs are
    # made before the socket cuts so no support material can obstruct a bore.
    for xc in centers_x:
        profile = [
            (xc - rib_base_half_length, rib_base_y),
            (xc + rib_base_half_length, rib_base_y),
            (xc, rib_tip_y)
        ]

        lower_rib = (
            cq.Workplane("XY", origin=(0, 0, 0))
            .polyline(profile)
            .close()
            .extrude(rib_thickness)
        )
        upper_rib = (
            cq.Workplane("XY", origin=(0, 0, 6.0))
            .polyline(profile)
            .close()
            .extrude(rib_thickness)
        )

        # Round the triangular rib outline where OCC permits it. Retain the
        # unfilleted rib if a local fillet is unsuitable near an intersection.
        try:
            lower_rib = lower_rib.edges("|Z").fillet(rib_fillet)
        except Exception as exc:
            print("Lower rib fillet skipped at x=", xc, exc)
        try:
            upper_rib = upper_rib.edges("|Z").fillet(rib_fillet)
        except Exception as exc:
            print("Upper rib fillet skipped at x=", xc, exc)

        result = result.union(lower_rib).union(upper_rib)

    # Recut all four coaxial blind sockets after unioning bosses, roots, and
    # ribs. This preserves four open annular rims and four bottoms at y=25.
    for xc in centers_x:
        cut_plane = cq.Plane(
            origin=(xc, opening_y, axis_z),
            xDir=(1, 0, 0),
            normal=(0, -1, 0)
        )
        socket_cut = (
            cq.Workplane(cut_plane)
            .circle(socket_radius)
            .extrude(opening_y - socket_bottom_y)
        )
        result = result.cut(socket_cut)

    final_shape = result.val()
    print("Final valid:", final_shape.isValid())
    print("Final solids:", len(final_shape.Solids()))
    print("Final faces:", len(final_shape.Faces()))
    print("Final volume:", final_shape.Volume())
    final_bb = final_shape.BoundingBox()
    print(
        "Final bbox: (%.3f,%.3f,%.3f)-(%.3f,%.3f,%.3f)" % (
            final_bb.xmin, final_bb.ymin, final_bb.zmin,
            final_bb.xmax, final_bb.ymax, final_bb.zmax
        )
    )
    return result
