def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)

    solids = imported.solids().vals()
    if not solids:
        raise ValueError("The imported STEP file contains no solid bodies")

    shape = solids[0]
    if len(solids) > 1:
        shape = solids[0].fuse(*solids[1:])

    bbox = shape.BoundingBox()
    tol = max(bbox.xlen, bbox.ylen, bbox.zlen) * 1.0e-5

    # Locate the existing recessed/lowered plateau. Its floor is expected to
    # be a planar ZX-parallel face lying inward from one of the Y extremes.
    plateau_candidates = []
    parallel_faces = []
    for face in shape.Faces():
        try:
            if face.geomType() != "PLANE":
                continue
            normal = face.normalAt()
            if abs(normal.y) < 0.95:
                continue
            center = face.Center()
            parallel_faces.append(face)
            inward_from_both_extremes = (
                center.y > bbox.ymin + tol and center.y < bbox.ymax - tol
            )
            if inward_from_both_extremes:
                plateau_candidates.append(face)
        except Exception:
            continue

    if plateau_candidates:
        plateau_face = max(plateau_candidates, key=lambda f: f.Area())
    elif parallel_faces:
        # Fallback for STEP models whose recessed floor is nearly coincident
        # with the bounding box because of numerical tolerances.
        plateau_face = max(parallel_faces, key=lambda f: f.Area())
    else:
        raise ValueError("Could not identify a planar lowered plateau parallel to the ZX plane")

    plateau_center = plateau_face.Center()
    plateau_bbox = plateau_face.BoundingBox()
    top_sign = 1.0 if plateau_center.y >= 0.0 else -1.0

    # Propagate the existing top-side recess to the opposite side. The common
    # volume of the part and its reflection about ZX (Y=0) retains the original
    # recess and introduces its exact counterpart on the bottom.
    mirrored = shape.mirror("XZ", (0.0, 0.0, 0.0))
    symmetric_shape = shape.intersect(mirrored).clean()
    if not symmetric_shape.isValid():
        raise ValueError("ZX-symmetrization produced an invalid solid")

    # Align the word with the longer in-plane direction of the plateau.
    if plateau_bbox.xlen >= plateau_bbox.zlen:
        text_x_dir = (1.0, 0.0, 0.0)
    else:
        text_x_dir = (0.0, 0.0, 1.0)

    text_normal = (0.0, top_sign, 0.0)

    # Start the lettering 0.02 mm inside the plateau to make the union robust,
    # while keeping its exposed upper surface exactly 1 mm above the plateau.
    overlap = 0.02
    text_origin = (
        plateau_center.x,
        plateau_center.y - top_sign * overlap,
        plateau_center.z,
    )
    text_plane = cq.Plane(
        origin=text_origin,
        xDir=text_x_dir,
        normal=text_normal,
    )

    text_wp = (
        cq.Workplane(text_plane)
        .text(
            "TOP",
            10.0,
            1.0 + overlap,
            font="Arial",
            kind="regular",
            halign="center",
            valign="center",
            combine=False,
            clean=True,
        )
    )

    text_solids = text_wp.solids().vals()
    if not text_solids:
        raise ValueError("CadQuery failed to create the embossed TOP lettering")

    result = symmetric_shape
    for text_solid in text_solids:
        result = result.fuse(text_solid)
    result = result.clean()

    print("EDIT SUMMARY")
    print(f"Original bbox Y: {bbox.ymin:.6f} to {bbox.ymax:.6f} mm")
    print(
        "Selected plateau center: "
        f"({plateau_center.x:.6f}, {plateau_center.y:.6f}, {plateau_center.z:.6f})"
    )
    print(f"Selected plateau area: {plateau_face.Area():.6f} mm^2")
    print(f"Top outward Y direction: {top_sign:+.0f}")
    print(f"Embossed text height: 10 mm; exposed raise: 1 mm; font: Arial")
    print(f"Result valid: {result.isValid()}; solids: {len(result.Solids())}")

    return cq.Workplane("XY").newObject([result])