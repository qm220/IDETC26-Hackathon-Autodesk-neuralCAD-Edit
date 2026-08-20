def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    solids = shape.Solids()
    if len(solids) < 2:
        raise ValueError("Expected at least two original solids: housing and scroll wheel")

    # Identify the housing by volume and preserve all other original solids.
    housing_index = max(range(len(solids)), key=lambda i: solids[i].Volume())
    housing = solids[housing_index]
    preserved_solids = [s for i, s in enumerate(solids) if i != housing_index]

    # Two ergonomic button footprints positioned symmetrically on the +Y top
    # surface, on opposite sides of the existing central scroll-wheel pocket.
    button_height = 2.0
    button_width = 20.0
    button_length = 40.0
    corner_radius = 5.0
    button_z_center = 48.0
    button_centers_x = (13.5, 42.0)

    # A copy translated exactly 2 mm in +Y provides conformal upper button
    # surfaces. Intersecting it with rounded footprint prisms limits the raised
    # geometry to the two requested button regions.
    shifted_housing = housing.translate((0.0, button_height, 0.0))
    modified_housing = housing
    generated_buttons = []

    for center_x in button_centers_x:
        button_plane = cq.Plane(
            origin=(center_x, -5.0, button_z_center),
            xDir=(1.0, 0.0, 0.0),
            normal=(0.0, 1.0, 0.0)
        )

        # Create the rounded rectangular prism using the supported 3D fillet
        # operation. The selected edges run along global Y, so their filleting
        # rounds only the footprint corners and retains the extrusion depth.
        footprint_wp = (
            cq.Workplane(button_plane)
            .rect(button_width, button_length)
            .extrude(45.0)
            .edges("|Y")
            .fillet(corner_radius)
        )
        footprint_prism = footprint_wp.val()

        button_cap = shifted_housing.intersect(footprint_prism)
        if button_cap.isNull() or button_cap.Volume() <= 1.0e-6:
            raise ValueError(
                "Failed to construct a button cap at x=" + str(center_x)
            )

        generated_buttons.append(button_cap)
        modified_housing = modified_housing.fuse(button_cap)

    try:
        modified_housing = modified_housing.clean()
    except Exception:
        pass

    final_solids = [modified_housing] + preserved_solids
    result = cq.Compound.makeCompound(final_solids)

    print("Loaded STEP:", input_file)
    print("Original solid count:", len(solids))
    print("Preserved non-housing solids:", len(preserved_solids))
    print("Generated click-button count:", len(generated_buttons))
    print("Button projection height: %.3f mm" % button_height)

    for index, button in enumerate(generated_buttons, start=1):
        bb = button.BoundingBox()
        print(
            "BUTTON %d: center_x=%.3f, footprint=%.3f x %.3f mm, "
            "bbox=x(%.3f,%.3f) y(%.3f,%.3f) z(%.3f,%.3f), volume=%.3f"
            % (
                index,
                button_centers_x[index - 1],
                button_width,
                button_length,
                bb.xmin,
                bb.xmax,
                bb.ymin,
                bb.ymax,
                bb.zmin,
                bb.zmax,
                button.Volume()
            )
        )

    print("Final shape valid:", result.isValid())
    return cq.Workplane(obj=result)