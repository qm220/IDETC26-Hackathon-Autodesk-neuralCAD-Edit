def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    solids = shape.Solids()
    if len(solids) < 2:
        raise ValueError("Expected the original mouse housing and scroll wheel as two solids")

    # Identify the large housing and preserve every other existing solid.
    housing = max(solids, key=lambda s: s.Volume())
    preserved_solids = [s for s in solids if s is not housing]

    # Create two ergonomic, rounded click-button footprints on the +Y user-facing
    # surface. They flank the existing scroll-wheel pocket without modifying it.
    button_height = 2.0
    button_width = 20.0
    button_length = 40.0
    corner_radius = 5.0
    button_z_center = 48.0
    button_centers_x = (13.5, 42.0)

    # Translating the original housing by exactly +2 mm and clipping it with each
    # footprint creates conformal button caps whose upper surfaces are exactly
    # 2 mm above the corresponding original housing surface.
    shifted_housing = cq.Workplane(obj=housing).translate((0, button_height, 0)).val()

    modified_housing = housing
    generated_buttons = []

    for center_x in button_centers_x:
        button_plane = cq.Plane(
            origin=(center_x, -5.0, button_z_center),
            xDir=(1.0, 0.0, 0.0),
            normal=(0.0, 1.0, 0.0)
        )
        footprint_prism = (
            cq.Workplane(button_plane)
            .rect(button_width, button_length)
            .vertices()
            .fillet2D(corner_radius)
            .extrude(45.0)
            .val()
        )

        button_cap = shifted_housing.intersect(footprint_prism)
        if button_cap.isNull() or button_cap.Volume() <= 0:
            raise ValueError("Failed to construct a click button on the housing surface")

        generated_buttons.append(button_cap)
        modified_housing = modified_housing.fuse(button_cap)

    try:
        modified_housing = modified_housing.clean()
    except Exception:
        pass

    final_solids = [modified_housing] + preserved_solids
    result = cq.Compound.makeCompound(final_solids)

    print(f"Loaded STEP: {input_file}")
    print(f"Original solids: {len(solids)}")
    print(f"Added click-button features: {len(generated_buttons)}")
    print(f"Specified button height: {button_height:.3f} mm")
    for index, button in enumerate(generated_buttons, start=1):
        bb = button.BoundingBox()
        print(
            f"BUTTON {index}: center_x={button_centers_x[index-1]:.3f}, "
            f"footprint={button_width:.3f} x {button_length:.3f} mm, "
            f"bbox=x({bb.xmin:.3f},{bb.xmax:.3f}) "
            f"y({bb.ymin:.3f},{bb.ymax:.3f}) "
            f"z({bb.zmin:.3f},{bb.zmax:.3f})"
        )
    print(f"Final shape valid: {result.isValid()}")

    return cq.Workplane(obj=result)
