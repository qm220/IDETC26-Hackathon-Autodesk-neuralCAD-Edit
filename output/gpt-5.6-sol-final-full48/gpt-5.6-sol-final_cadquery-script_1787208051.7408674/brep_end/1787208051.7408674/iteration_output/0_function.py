def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    base_shape = imported.val()
    bbox = base_shape.BoundingBox()

    y_min = bbox.ymin
    y_max = bbox.ymax
    y_mid = 0.5 * (y_min + y_max)

    # Locate the planar floor of the existing top-side recessed plateau.
    floor_candidates = []
    for face in base_shape.Faces():
        fb = face.BoundingBox()
        try:
            is_plane = face.geomType() == "PLANE"
        except Exception:
            is_plane = False
        if (
            is_plane
            and fb.ylen < 1.0e-5
            and fb.center.y > y_mid
            and fb.center.y < y_max - 0.05
        ):
            floor_candidates.append(face)

    if not floor_candidates:
        raise ValueError("Could not identify the existing top plateau floor")

    # The recess floor is the largest horizontal interior planar face below the top skin.
    top_floor = max(floor_candidates, key=lambda f: f.Area())
    floor_bb = top_floor.BoundingBox()
    top_floor_y = floor_bb.center.y
    recess_depth = y_max - top_floor_y

    if recess_depth <= 0.0:
        raise ValueError("Detected top plateau has an invalid recess depth")

    # Reuse the exact existing recess boundary, translated to the bottom skin, so the
    # new pocket is congruent with the top pocket about the ZX midplane.
    bottom_wire = top_floor.outerWire().translate(
        cq.Vector(0.0, y_min - top_floor_y, 0.0)
    )
    bottom_cutter = cq.Solid.extrudeLinear(
        bottom_wire, [], cq.Vector(0.0, recess_depth, 0.0)
    )
    result_shape = base_shape.cut(bottom_cutter)

    # Center the label using the existing plateau floor rather than the whole wrench.
    text_x = floor_bb.center.x
    text_z = floor_bb.center.z

    # Local text X runs along global +Z (the handle length), local text Y runs along
    # global +X, and the extrusion normal points toward global +Y.
    text_plane = cq.Plane(
        origin=(text_x, top_floor_y, text_z),
        xDir=(0.0, 0.0, 1.0),
        normal=(0.0, 1.0, 0.0),
    )

    # Prefer an installed Microsoft Arial font file when available.
    arial_paths = [
        "/usr/share/fonts/truetype/msttcorefonts/Arial.ttf",
        "/usr/share/fonts/truetype/msttcorefonts/arial.ttf",
        "/usr/share/fonts/truetype/msttcorefonts/Arial_Regular.ttf",
        "/usr/share/fonts/truetype/msttcorefonts/Arial_Bold.ttf",
    ]
    font_path = next((p for p in arial_paths if os.path.exists(p)), None)

    text_kwargs = dict(
        txt="TOP",
        fontsize=10.0,
        distance=1.0,
        font="Arial",
        kind="regular",
        halign="center",
        valign="center",
        combine=False,
        clean=True,
    )
    if font_path is not None:
        text_kwargs["fontPath"] = font_path

    try:
        text_result = cq.Workplane(text_plane).text(**text_kwargs)
    except Exception as exc:
        # Liberation Sans is metrically compatible with Arial and is used only if
        # Arial is unavailable in the execution environment.
        print("Arial unavailable; using Liberation Sans fallback:", exc)
        text_kwargs.pop("fontPath", None)
        text_kwargs["font"] = "Liberation Sans"
        text_result = cq.Workplane(text_plane).text(**text_kwargs)

    # Fuse each disconnected letter body into the wrench. The 1 mm emboss starts at
    # the Y=14 mm plateau floor and ends flush with the nominal Y=15 mm top skin.
    text_solids = text_result.solids().vals()
    if not text_solids:
        raise ValueError("Text generation produced no solids")
    for text_solid in text_solids:
        result_shape = result_shape.fuse(text_solid)

    print("Original Y extent:", y_min, "to", y_max)
    print("Top plateau floor Y:", top_floor_y)
    print("Mirrored bottom plateau floor Y:", y_min + recess_depth)
    print("Plateau depth:", recess_depth)
    print("Embossed centered text: TOP, nominal Arial height 10 mm, rise 1 mm")
    print("Result valid:", result_shape.isValid())

    return cq.Workplane(obj=result_shape)