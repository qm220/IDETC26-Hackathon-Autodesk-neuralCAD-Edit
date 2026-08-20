def my_cad_function(args):
    import os

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    # Inspect and bind the planned FACE indices to the imported STEP geometry.
    print("Loaded STEP:", input_file)
    print("Valid:", shape.isValid(), "solids:", len(shape.Solids()), "faces:", len(shape.Faces()))
    bb = shape.BoundingBox()
    print("Model bbox: x=(%.6f, %.6f), y=(%.6f, %.6f), z=(%.6f, %.6f)" %
          (bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax))

    faces = shape.Faces()
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

    # Locate the existing +Y lowered plateau floor (planned FACE 1) from its
    # actual imported geometry rather than relying solely on its STEP index.
    floor_face = None
    floor_score = None
    for i, face in enumerate(faces):
        fb = face.BoundingBox()
        dx = fb.xmax - fb.xmin
        dy = fb.ymax - fb.ymin
        dz = fb.zmax - fb.zmin
        try:
            is_plane = face.geomType() == "PLANE"
        except Exception:
            is_plane = False
        if is_plane and dy < 1.0e-5 and dz > 80.0 and 12.0 < dx < 17.0:
            # Prefer the horizontal face one millimetre below the y-max face.
            score = abs(fb.ymin - (bb.ymax - 1.0))
            if floor_score is None or score < floor_score:
                floor_face = face
                floor_score = score

    if floor_face is None:
        raise ValueError("Could not identify the existing handle plateau floor")

    pbb = floor_face.BoundingBox()
    x_min, x_max = pbb.xmin, pbb.xmax
    z_min, z_max = pbb.zmin, pbb.zmax
    x_center = 0.5 * (x_min + x_max)
    z_center = 0.5 * (z_min + z_max)
    pocket_width = x_max - x_min
    pocket_length = z_max - z_min
    top_floor_y = pbb.ymin

    print("Bound existing plateau floor at y=%.6f" % top_floor_y)
    print("Plateau extents: x=(%.6f, %.6f), z=(%.6f, %.6f), center=(%.6f, %.6f)" %
          (x_min, x_max, z_min, z_max, x_center, z_center))

    # Reproduce the existing rounded-rectangle pocket on the opposite broad
    # face. The imported body spans y=0..15; this cutter grows inward in +Y.
    bottom_y = bb.ymin
    bottom_plane = cq.Plane(
        origin=(x_center, bottom_y, z_center),
        xDir=(1, 0, 0),
        normal=(0, 1, 0)
    )
    bottom_cutter = (
        cq.Workplane(bottom_plane)
        .roundedRect(pocket_width, pocket_length, 1.0)
        .extrude(1.0)
    )
    edited = model.cut(bottom_cutter)

    # Emboss TOP on the existing +Y plateau. Local text X follows global Z so
    # the word runs along the long direction; local text Y follows global X.
    text_plane = cq.Plane(
        origin=(x_center, top_floor_y, z_center),
        xDir=(0, 0, 1),
        normal=(0, 1, 0)
    )

    try:
        text_solid = (
            cq.Workplane(text_plane)
            .text("TOP", 10.0, 1.0, font="Arial",
                  halign="center", valign="center", combine=False)
        )
        print("Generated text using Arial")
    except Exception as exc:
        # Liberation Sans is metrically compatible with Arial and is commonly
        # available on Linux CadQuery runners when Microsoft fonts are absent.
        print("Arial unavailable; using Liberation Sans fallback:", exc)
        text_solid = (
            cq.Workplane(text_plane)
            .text("TOP", 10.0, 1.0, font="Liberation Sans",
                  halign="center", valign="center", combine=False)
        )

    tbb = text_solid.val().BoundingBox()
    print("Text bbox: x=(%.4f,%.4f), y=(%.4f,%.4f), z=(%.4f,%.4f)" %
          (tbb.xmin, tbb.xmax, tbb.ymin, tbb.ymax, tbb.zmin, tbb.zmax))

    # The 10 mm glyph height is smaller than the approximately 14.4 mm pocket
    # width, and the word length is well within the approximately 91 mm pocket.
    margin = 0.05
    if (tbb.xmin < x_min + margin or tbb.xmax > x_max - margin or
            tbb.zmin < z_min + margin or tbb.zmax > z_max - margin):
        raise ValueError("Embossed text does not fit wholly inside the plateau")

    edited = edited.union(text_solid)

    # Rebase the physical thickness midplane from y=7.5 onto the global ZX
    # datum plane y=0. The two plateau floors then lie at y=+/-6.5 mm and the
    # untouched broad faces at y=+/-7.5 mm.
    mid_y = 0.5 * (bb.ymin + bb.ymax)
    edited = edited.translate((0, -mid_y, 0))

    final_shape = edited.val()
    print("Final valid:", final_shape.isValid(),
          "solids:", len(final_shape.Solids()),
          "volume:", final_shape.Volume())
    fbb = final_shape.BoundingBox()
    print("Final y extents=(%.6f, %.6f), symmetry datum y=0" %
          (fbb.ymin, fbb.ymax))
    return edited