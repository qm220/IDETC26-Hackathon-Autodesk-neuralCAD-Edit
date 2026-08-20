def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    print("Loaded STEP:", input_file)
    print("Valid:", shape.isValid(), "solids:", len(shape.Solids()), "faces:", len(shape.Faces()))
    bb = shape.BoundingBox()
    print("Model bbox: x=(%.6f, %.6f), y=(%.6f, %.6f), z=(%.6f, %.6f)" %
          (bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax))

    # Inspect imported faces and bind the planned plateau floor to geometry.
    faces = shape.Faces()
    floor_face = None
    floor_score = None
    for i, face in enumerate(faces):
        fb = face.BoundingBox()
        c = face.Center()
        try:
            geom = face.geomType()
        except Exception:
            geom = "UNKNOWN"
        print("FACE %d: %s center=(%.4f,%.4f,%.4f) bbox=[%.4f,%.4f]x[%.4f,%.4f]x[%.4f,%.4f] area=%.4f" %
              (i, geom, c.x, c.y, c.z, fb.xmin, fb.xmax, fb.ymin, fb.ymax,
               fb.zmin, fb.zmax, face.Area()))

        dx = fb.xmax - fb.xmin
        dy = fb.ymax - fb.ymin
        dz = fb.zmax - fb.zmin
        if geom == "PLANE" and dy < 1.0e-5 and dz > 80.0 and 12.0 < dx < 17.0:
            score = abs(fb.ymin - (bb.ymax - 1.0))
            if floor_score is None or score < floor_score:
                floor_face = face
                floor_score = score

    if floor_face is None:
        raise ValueError("Could not identify the existing top lowered plateau floor")

    pbb = floor_face.BoundingBox()
    x_min, x_max = pbb.xmin, pbb.xmax
    z_min, z_max = pbb.zmin, pbb.zmax
    x_center = 0.5 * (x_min + x_max)
    z_center = 0.5 * (z_min + z_max)
    plateau_width = x_max - x_min
    plateau_length = z_max - z_min
    top_floor_y = pbb.ymin
    recess_depth = bb.ymax - top_floor_y
    corner_radius = 1.0

    print("Bound top plateau floor at y=%.6f" % top_floor_y)
    print("Plateau extents: x=(%.6f, %.6f), z=(%.6f, %.6f), center=(%.6f, %.6f)" %
          (x_min, x_max, z_min, z_max, x_center, z_center))
    print("Mirrored bottom recess depth: %.6f" % recess_depth)

    if recess_depth <= 0.0:
        raise ValueError("Invalid top plateau recess depth")

    # Add the matching lowered plateau to the bottom by removing a rounded-
    # rectangle volume from y=0 inward. This mirrors the existing y=14..15
    # recess about the original thickness midplane y=7.5. Primitive solids are
    # used because this CadQuery installation has no Workplane.roundedRect().
    cutter_parts = []

    # Central strips of the rounded rectangle.
    cutter_parts.append(cq.Solid.makeBox(
        plateau_width - 2.0 * corner_radius,
        recess_depth,
        plateau_length,
        cq.Vector(x_min + corner_radius, bb.ymin, z_min)
    ))
    cutter_parts.append(cq.Solid.makeBox(
        plateau_width,
        recess_depth,
        plateau_length - 2.0 * corner_radius,
        cq.Vector(x_min, bb.ymin, z_min + corner_radius)
    ))

    # Four radius-1 mm corner cylinders, with axes along global Y.
    for cx in (x_min + corner_radius, x_max - corner_radius):
        for cz in (z_min + corner_radius, z_max - corner_radius):
            cutter_parts.append(cq.Solid.makeCylinder(
                corner_radius,
                recess_depth,
                cq.Vector(cx, bb.ymin, cz),
                cq.Vector(0, 1, 0)
            ))

    edited = model
    for part in cutter_parts:
        edited = edited.cut(cq.Workplane("XY").newObject([part]))

    # Emboss TOP from the existing top plateau floor toward +Y. Local text X
    # follows global Z, so the word runs along the long direction of the
    # plateau; local text Y follows global X.
    text_plane = cq.Plane(
        origin=(x_center, top_floor_y, z_center),
        xDir=(0, 0, 1),
        normal=(0, 1, 0)
    )

    try:
        text_wp = cq.Workplane(text_plane).text(
            "TOP", 10.0, 1.0,
            font="Arial",
            halign="center",
            valign="center",
            combine=False
        )
        print("Generated text using Arial")
    except Exception as exc:
        print("Arial unavailable; using metrically compatible Liberation Sans:", exc)
        text_wp = cq.Workplane(text_plane).text(
            "TOP", 10.0, 1.0,
            font="Liberation Sans",
            halign="center",
            valign="center",
            combine=False
        )

    text_shape = text_wp.val()
    tbb = text_shape.BoundingBox()
    print("Text bbox: x=(%.4f,%.4f), y=(%.4f,%.4f), z=(%.4f,%.4f)" %
          (tbb.xmin, tbb.xmax, tbb.ymin, tbb.ymax, tbb.zmin, tbb.zmax))

    # Verify the complete text footprint remains inside the plateau bounds.
    margin = 0.05
    if (tbb.xmin < x_min + margin or tbb.xmax > x_max - margin or
            tbb.zmin < z_min + margin or tbb.zmax > z_max - margin):
        raise ValueError("Embossed TOP text does not fit within the plateau boundary")
    if abs(tbb.ymin - top_floor_y) > 1.0e-4 or abs(tbb.ymax - (top_floor_y + 1.0)) > 1.0e-4:
        raise ValueError("Embossed text does not have the required 1 mm raised height")

    edited = edited.union(text_wp)

    # Place the original thickness midplane on the global ZX datum plane y=0.
    # The matching plateau floors are consequently at y=-6.5 and y=+6.5.
    mid_y = 0.5 * (bb.ymin + bb.ymax)
    edited = edited.translate((0, -mid_y, 0))

    final_shape = edited.val()
    fbb = final_shape.BoundingBox()
    print("Final valid:", final_shape.isValid(),
          "solids:", len(final_shape.Solids()),
          "volume:", final_shape.Volume())
    print("Final bbox y=(%.6f, %.6f); ZX symmetry datum y=0" %
          (fbb.ymin, fbb.ymax))

    if not final_shape.isValid() or len(final_shape.Solids()) != 1:
        raise ValueError("Final edited wrench is not one valid solid")

    return edited