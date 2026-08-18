def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    body = imported.val()

    bbox = body.BoundingBox()
    ymin, ymax = bbox.ymin, bbox.ymax
    print("Input valid:", body.isValid())
    print("Bounding box: X[%.3f, %.3f] Y[%.3f, %.3f] Z[%.3f, %.3f]" % (
        bbox.xmin, bbox.xmax, ymin, ymax, bbox.zmin, bbox.zmax
    ))

    # Locate the existing shallow top recess floor. It is the largest planar
    # thickness-normal face approximately 1 mm below the maximum-Y upper land.
    horizontal_faces = []
    for face in body.Faces():
        try:
            if face.geomType() != "PLANE":
                continue
            fb = face.BoundingBox()
            if (fb.ymax - fb.ymin) > 1.0e-4:
                continue
            cy = face.Center().y
            horizontal_faces.append((cy, face.Area(), face))
            print("Horizontal face: y=%.4f area=%.4f" % (cy, face.Area()))
        except Exception:
            pass

    nominal_depth = 1.0
    floor_candidates = [
        item for item in horizontal_faces
        if abs(item[0] - (ymax - nominal_depth)) < 0.25
    ]
    if not floor_candidates:
        # Fallback: choose the largest horizontal face strictly below the top
        # and above the thickness midplane.
        floor_candidates = [
            item for item in horizontal_faces
            if item[0] < ymax - 0.1 and item[0] > (ymin + ymax) * 0.5
        ]
    if not floor_candidates:
        raise ValueError("Could not identify the top recessed plateau floor")

    floor_y, floor_area, floor_face = max(floor_candidates, key=lambda item: item[1])
    recess_depth = ymax - floor_y
    floor_center = floor_face.Center()
    print("Selected top plateau floor: y=%.4f area=%.4f center=(%.4f, %.4f, %.4f)" % (
        floor_y, floor_area, floor_center.x, floor_center.y, floor_center.z
    ))
    print("Measured recess depth: %.4f mm" % recess_depth)

    # Mirror the top plateau footprint onto the bottom and pocket it inward by
    # the measured top recess depth. A tiny overrun avoids coincident-face
    # failures at the original bottom surface.
    eps = 0.002
    shift_y = (ymin - eps) - floor_y
    bottom_outer = floor_face.outerWire().translate((0, shift_y, 0))
    bottom_inners = [wire.translate((0, shift_y, 0)) for wire in floor_face.innerWires()]
    bottom_cutter = cq.Solid.extrudeLinear(
        bottom_outer,
        bottom_inners,
        cq.Vector(0, recess_depth + 2.0 * eps, 0)
    )
    body = body.cut(bottom_cutter)
    print("Added mirrored bottom recess; target floor y=%.4f" % (ymin + recess_depth))

    # Place TOP along the longitudinal Z direction. Local text X is global Z,
    # local text Y is global X, and the extrusion normal is global +Y.
    # Embed the lettering very slightly into the floor while keeping its upper
    # surface at the original upper-land height.
    text_plane = cq.Plane(
        origin=(floor_center.x, floor_y - eps, floor_center.z),
        xDir=(0, 0, 1),
        normal=(0, 1, 0)
    )

    try:
        text_wp = cq.Workplane(text_plane).text(
            "TOP",
            10.0,
            recess_depth + eps,
            combine=False,
            clean=True,
            font="Arial",
            kind="regular",
            halign="center",
            valign="center"
        )
        used_font = "Arial"
    except Exception as exc:
        print("Arial font lookup failed; using metrically compatible fallback:", exc)
        text_wp = cq.Workplane(text_plane).text(
            "TOP",
            10.0,
            recess_depth + eps,
            combine=False,
            clean=True,
            font="Liberation Sans",
            kind="regular",
            halign="center",
            valign="center"
        )
        used_font = "Liberation Sans"

    text_solids = text_wp.solids().vals()
    if not text_solids:
        raise ValueError("Text operation did not generate any solids")

    for text_solid in text_solids:
        body = body.fuse(text_solid)

    body = body.clean()
    out_bbox = body.BoundingBox()
    print("Embossed TOP using %s; generated %d letter solids" % (used_font, len(text_solids)))
    print("Output valid:", body.isValid())
    print("Output Y range: %.4f to %.4f" % (out_bbox.ymin, out_bbox.ymax))
    print("Output volume: %.4f mm^3" % body.Volume())
    return cq.Workplane(obj=body)