def my_cad_function(args):
    import os

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    source_shape = imported.val()

    solids = list(source_shape.Solids())
    if not solids:
        raise ValueError("The input STEP file contains no solids")

    # The housing is the largest solid; the smaller solid is the scroll wheel.
    solids_by_volume = sorted(solids, key=lambda s: s.Volume(), reverse=True)
    housing = solids_by_volume[0]
    other_solids = solids_by_volume[1:]

    hb = housing.BoundingBox()
    width_x = hb.xmax - hb.xmin
    height_y = hb.ymax - hb.ymin
    length_z = hb.zmax - hb.zmin
    center_x = 0.5 * (hb.xmin + hb.xmax)

    # Locate the scroll wheel from the largest of the remaining small solids.
    if other_solids:
        wheel = other_solids[0]
        wb = wheel.BoundingBox()
        wheel_z = 0.5 * (wb.zmin + wb.zmax)
        wheel_half_x = max(abs(wb.xmin - center_x), abs(wb.xmax - center_x))
    else:
        wheel_z = hb.zmin + 0.52 * length_z
        wheel_half_x = 0.055 * width_x

    # Positive Z is the front. The buttons extend from just behind the wheel
    # toward the nose while remaining inset from the housing side and nose.
    z_back = max(hb.zmin + 0.38 * length_z, wheel_z - 0.10 * length_z)
    z_front = hb.zmax - 0.055 * length_z
    if z_front <= z_back + 0.20 * length_z:
        z_back = hb.zmin + 0.42 * length_z
        z_front = hb.zmax - 0.06 * length_z

    z_mid = z_back + 0.58 * (z_front - z_back)
    center_gap = max(wheel_half_x + 1.5, 0.085 * width_x)
    outer_back = 0.31 * width_x
    outer_mid = 0.43 * width_x
    outer_front = 0.30 * width_x

    # Keep all footprint coordinates safely within the body's lateral bounds.
    available_half_width = 0.5 * width_x
    outer_back = min(outer_back, available_half_width - 0.09 * width_x)
    outer_mid = min(outer_mid, available_half_width - 0.055 * width_x)
    outer_front = min(outer_front, available_half_width - 0.11 * width_x)

    def make_footprint(side):
        # side=-1 creates the negative-X button; side=+1 mirrors it.
        x_inner = center_x + side * center_gap
        x_back = center_x + side * outer_back
        x_mid = center_x + side * outer_mid
        x_front = center_x + side * outer_front

        return (
            cq.Workplane("XZ")
            .moveTo(x_inner, z_back)
            .lineTo(x_back, z_back)
            .spline([
                (x_mid, z_mid),
                (x_front, z_front),
            ])
            .lineTo(x_inner, z_front)
            .lineTo(x_inner, z_back)
            .close()
            .extrude(2.0 * (height_y + 10.0), both=True)
            .val()
        )

    # A translated copy of the housing minus the original housing produces a
    # surface-conforming cap whose maximum vertical protrusion is exactly 2 mm.
    raised_housing = housing.translate((0, 2.0, 0))

    # Restrict the operation to the upper half so translated underside or side
    # surfaces cannot become part of a button.
    upper_cut_y = hb.ymin + 0.48 * height_y
    upper_slab = cq.Solid.makeBox(
        width_x + 20.0,
        (hb.ymax + 5.0) - upper_cut_y,
        length_z + 20.0,
        cq.Vector(hb.xmin - 10.0, upper_cut_y, hb.zmin - 10.0),
    )

    raised_skin = raised_housing.cut(housing).intersect(upper_slab)
    button_solids = []

    for side in (-1, 1):
        footprint = make_footprint(side)
        raw_button = raised_skin.intersect(footprint)
        candidates = [s for s in raw_button.Solids() if s.Volume() > 0.05]
        if not candidates:
            raise ValueError("A button footprint did not intersect the upper housing")

        # Normally each footprint yields one cap. Keep the largest connected
        # result to reject any minute artifacts from translated B-spline faces.
        button = max(candidates, key=lambda s: s.Volume())

        # A small matching edge blend removes sharp exposed boundaries while
        # retaining a broad central region at the prescribed 2 mm height.
        try:
            button = button.fillet(min(0.35, 0.12 * height_y), button.Edges())
        except Exception:
            pass

        button_solids.append(button)

    result_solids = solids + button_solids
    result = cq.Compound.makeCompound(result_solids)

    print("Input solids:", len(solids))
    print("Housing bbox: X %.3f..%.3f, Y %.3f..%.3f, Z %.3f..%.3f" %
          (hb.xmin, hb.xmax, hb.ymin, hb.ymax, hb.zmin, hb.zmax))
    print("Wheel reference Z: %.3f; center clearance half-width: %.3f" %
          (wheel_z, center_gap))
    print("Created two independent surface-conforming click buttons, each raised 2.0 mm")
    print("Output solids:", len(result.Solids()), "Valid:", result.isValid())

    return cq.Workplane(obj=result)