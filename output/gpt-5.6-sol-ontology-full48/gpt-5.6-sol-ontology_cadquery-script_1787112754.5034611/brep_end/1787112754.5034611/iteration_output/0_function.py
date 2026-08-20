def my_cad_function(args):
    import os

    input_file = os.path.expanduser(args["input_file"])
    model_wp = cq.importers.importStep(input_file)
    model = model_wp.val() if hasattr(model_wp, "val") else model_wp

    # Inspect the imported STEP topology and geometrically bind the planned
    # FACE references rather than relying solely on unstable face indices.
    bbox = model.BoundingBox()
    print("Imported model valid:", model.isValid())
    print("Imported volume: %.6f mm^3" % model.Volume())
    print("Face count:", len(model.Faces()))
    print("Bounds: X[%.6f, %.6f] Y[%.6f, %.6f] Z[%.6f, %.6f]" %
          (bbox.xmin, bbox.xmax, bbox.ymin, bbox.ymax, bbox.zmin, bbox.zmax))

    faces = model.Faces()
    for i, face in enumerate(faces):
        fb = face.BoundingBox()
        c = face.Center()
        gt = face.geomType()
        # Print the planned face indices and all faces near either edited region.
        if i in (44, 46, 68, 74, 77, 78, 79, 89, 90) or fb.ymin <= bbox.ymin + 0.15:
            print("FACE %d: type=%s area=%.6f center=(%.6f,%.6f,%.6f) "
                  "bbox=(%.6f,%.6f; %.6f,%.6f; %.6f,%.6f)" %
                  (i, gt, face.Area(), c.x, c.y, c.z,
                   fb.xmin, fb.xmax, fb.ymin, fb.ymax, fb.zmin, fb.zmax))

    # Geometrically identify the two existing coaxial pin-bore walls.
    pin_y = 3.510000
    pin_z = 2.943179
    bore_candidates = []
    for i, face in enumerate(faces):
        if face.geomType() != "CYLINDER":
            continue
        fb = face.BoundingBox()
        c = face.Center()
        # Existing bore segments lie in the two narrow clevis-ear X ranges and
        # have their face centers on the common pin axis.
        if (abs(c.y - pin_y) < 0.15 and abs(c.z - pin_z) < 0.15 and
                fb.xmax - fb.xmin < 1.0):
            bore_candidates.append(i)
    print("Geometrically located clevis bore candidate faces:", bore_candidates)

    # Operation 1: enlarge both existing coaxial 1.5 mm bores to one continuous
    # 1.7 mm diameter passage. The cutter is deliberately overextended beyond
    # both sides of the imported solid.
    hole_radius = 0.85
    hole_start_x = bbox.xmin - 1.0
    hole_length = (bbox.xmax - bbox.xmin) + 2.0
    hole_cutter = cq.Solid.makeCylinder(
        hole_radius,
        hole_length,
        cq.Vector(hole_start_x, pin_y, pin_z),
        cq.Vector(1, 0, 0)
    )
    edited = model.cut(hole_cutter)
    print("Volume after 1.7 mm connecting-hole cut: %.6f mm^3" % edited.Volume())

    # Operation 2: apply a configurable cross-hatched groove pattern to the
    # primary underside mounting face. Here 0.1 mm is interpreted as depth.
    groove_depth = 0.10
    groove_width = 0.10
    groove_pitch = 0.70
    underside_y = bbox.ymin

    # Create diagonal rectangular channels in the XZ mounting plane. Each bar
    # spans the entire footprint; intersection with the solid clips it to the
    # actual FACE 77 perimeter.
    cx = 0.5 * (bbox.xmin + bbox.xmax)
    cz = 0.5 * (bbox.zmin + bbox.zmax)
    span_x = bbox.xmax - bbox.xmin
    span_z = bbox.zmax - bbox.zmin
    bar_length = 2.5 * max(span_x, span_z)
    pattern_span = span_x + span_z + 4.0
    y_center = underside_y + groove_depth * 0.5

    groove_tool = None
    count = int(pattern_span / groove_pitch) + 2
    for angle in (45.0, -45.0):
        for n in range(-count, count + 1):
            offset = n * groove_pitch
            # Before rotation, bars run along global X and are offset in Z.
            bar = (cq.Workplane("XY")
                   .box(bar_length, groove_depth, groove_width, centered=(True, True, True))
                   .translate((cx, y_center, cz + offset))
                   .rotate((cx, y_center, cz), (cx, y_center + 1.0, cz), angle)
                   .val())
            groove_tool = bar if groove_tool is None else groove_tool.fuse(bar)

    # Keep grooves clear of all four mounting through-bores so their cylindrical
    # walls are not nicked. The clearance radius exceeds the existing 0.4 mm
    # bore radius while retaining ample textured seating area.
    mounting_centers = [
        (0.293627, -1.526470),
        (0.293627,  1.473530),
        (11.953627, 1.123530),
        (11.953627, -2.986470),
    ]
    hole_clearance_radius = 0.55
    exclusion = None
    for hx, hz in mounting_centers:
        cyl = cq.Solid.makeCylinder(
            hole_clearance_radius,
            groove_depth + 0.4,
            cq.Vector(hx, underside_y - 0.2, hz),
            cq.Vector(0, 1, 0)
        )
        exclusion = cyl if exclusion is None else exclusion.fuse(cyl)
    groove_tool = groove_tool.cut(exclusion)

    result = edited.cut(groove_tool)
    print("Final valid:", result.isValid())
    print("Final volume: %.6f mm^3" % result.Volume())
    print("Final solids:", len(result.Solids()))
    print("Applied grooves: depth=%.3f width=%.3f pitch=%.3f mm, cross-hatch=+/-45 deg" %
          (groove_depth, groove_width, groove_pitch))

    return cq.Workplane(obj=result)
