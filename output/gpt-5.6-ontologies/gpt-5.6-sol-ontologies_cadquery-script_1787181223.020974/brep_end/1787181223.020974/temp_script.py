def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)

    solids = imported.solids().vals()
    if not solids:
        raise ValueError("The imported STEP file contains no solid bodies")

    shape = solids[0]
    if len(solids) > 1:
        shape = solids[0].fuse(*solids[1:]).clean()

    bbox = shape.BoundingBox()
    y_mid = 0.5 * (bbox.ymin + bbox.ymax)
    tol = max(bbox.xlen, bbox.ylen, bbox.zlen) * 1.0e-5

    # Find the existing lowered plateau floor. It is a large planar face
    # parallel to ZX and positioned inward from an exterior Y surface.
    plateau_candidates = []
    for face in shape.Faces():
        try:
            if face.geomType() != "PLANE":
                continue
            normal = face.normalAt()
            if abs(normal.y) < 0.95:
                continue
            center = face.Center()
            if bbox.ymin + tol < center.y < bbox.ymax - tol:
                plateau_candidates.append(face)
        except Exception:
            continue

    if not plateau_candidates:
        raise ValueError("Could not identify the existing lowered plateau floor")

    plateau_face = max(plateau_candidates, key=lambda f: f.Area())
    plateau_center = plateau_face.Center()
    plateau_bbox = plateau_face.BoundingBox()
    top_sign = 1.0 if plateau_center.y >= y_mid else -1.0

    # The ZX symmetry plane is the thickness midplane of the imported part,
    # not necessarily global Y=0. Intersecting the part with its reflection
    # preserves the existing plateau and creates its corresponding recess on
    # the opposite side.
    reflected = shape.mirror("XZ", (0.0, y_mid, 0.0))
    symmetric_shape = shape.intersect(reflected).clean()
    if not symmetric_shape.isValid() or not symmetric_shape.Solids():
        raise ValueError("Mid-thickness ZX symmetrization produced no valid solid")

    # Orient the lettering along the plateau's longer in-plane direction.
    if plateau_bbox.xlen >= plateau_bbox.zlen:
        text_x_dir = (1.0, 0.0, 0.0)
    else:
        text_x_dir = (0.0, 0.0, 1.0)

    overlap = 0.02
    text_origin = (
        plateau_center.x,
        plateau_center.y - top_sign * overlap,
        plateau_center.z,
    )
    text_plane = cq.Plane(
        origin=text_origin,
        xDir=text_x_dir,
        normal=(0.0, top_sign, 0.0),
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
        raise ValueError("CadQuery failed to create the Arial TOP lettering")

    # Build an exact outward prism from the plateau face. Intersecting the
    # lettering with this prism guarantees that its entire footprint remains
    # inside the plateau boundary while retaining the specified 1 mm raise.
    shift = cq.Vector(0.0, -top_sign * overlap, 0.0)
    outer_wire = plateau_face.outerWire().translate(shift)
    inner_wires = [wire.translate(shift) for wire in plateau_face.innerWires()]
    allowed_text_volume = cq.Solid.extrudeLinear(
        outer_wire,
        inner_wires,
        cq.Vector(0.0, top_sign * (1.0 + overlap), 0.0),
    )

    contained_text = []
    original_text_volume = 0.0
    contained_text_volume = 0.0
    for text_solid in text_solids:
        original_text_volume += text_solid.Volume()
        clipped = text_solid.intersect(allowed_text_volume).clean()
        if clipped.Solids():
            contained_text.append(clipped)
            contained_text_volume += clipped.Volume()

    if not contained_text:
        raise ValueError("The centered text does not overlap the selected plateau")

    containment_ratio = contained_text_volume / original_text_volume
    if containment_ratio < 0.999:
        raise ValueError(
            "The 10 mm centered TOP text does not fit fully within the plateau "
            f"(contained volume ratio {containment_ratio:.6f})"
        )

    result = symmetric_shape
    for text_shape in contained_text:
        result = result.fuse(text_shape)
    result = result.clean()

    if not result.isValid():
        raise ValueError("Final edited model is invalid")
    if len(result.Solids()) != 1:
        raise ValueError(
            f"Embossed text did not unite with the part; final solid count is {len(result.Solids())}"
        )

    result_bbox = result.BoundingBox()
    print("EDIT SUMMARY")
    print(f"Original Y range: {bbox.ymin:.6f} to {bbox.ymax:.6f} mm")
    print(f"ZX symmetry plane: Y={y_mid:.6f} mm")
    print(
        "Plateau center: "
        f"({plateau_center.x:.6f}, {plateau_center.y:.6f}, {plateau_center.z:.6f})"
    )
    print(f"Plateau area: {plateau_face.Area():.6f} mm^2")
    print(f"Top direction: {top_sign:+.0f}Y")
    print(f"Text containment ratio: {containment_ratio:.6f}")
    print("Text: TOP; font: Arial; height: 10 mm; raise: 1 mm")
    print(f"Final Y range: {result_bbox.ymin:.6f} to {result_bbox.ymax:.6f} mm")
    print(f"Result valid: {result.isValid()}; solids: {len(result.Solids())}")

    return cq.Workplane("XY").newObject([result])