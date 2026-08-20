def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    source_shape = imported.val()

    solids = list(source_shape.Solids())
    if not solids:
        raise ValueError("The input STEP file contains no solids")

    solids_by_volume = sorted(solids, key=lambda s: s.Volume(), reverse=True)
    housing = solids_by_volume[0]
    remaining = solids_by_volume[1:]

    hb = housing.BoundingBox()
    width_x = hb.xmax - hb.xmin
    height_y = hb.ymax - hb.ymin
    length_z = hb.zmax - hb.zmin
    center_x = 0.5 * (hb.xmin + hb.xmax)

    if remaining:
        wheel = remaining[0]
        wb = wheel.BoundingBox()
        wheel_z = 0.5 * (wb.zmin + wb.zmax)
        wheel_half_x = max(abs(wb.xmin - center_x), abs(wb.xmax - center_x))
    else:
        wheel_z = hb.zmin + 0.55 * length_z
        wheel_half_x = 0.055 * width_x

    # Broad conventional left and right mouse-button footprints extending
    # forward from the scroll-wheel region.
    z_back = max(hb.zmin + 0.40 * length_z, wheel_z - 0.11 * length_z)
    z_front = hb.zmax - 0.065 * length_z
    if z_front <= z_back + 0.18 * length_z:
        z_back = hb.zmin + 0.43 * length_z
        z_front = hb.zmax - 0.055 * length_z
    z_mid = z_back + 0.58 * (z_front - z_back)

    center_gap = max(wheel_half_x + 1.2, 0.075 * width_x)
    outer_back = min(0.31 * width_x, 0.40 * width_x)
    outer_mid = min(0.425 * width_x, 0.445 * width_x)
    outer_front = min(0.30 * width_x, 0.39 * width_x)

    def footprint_solid(side):
        x_inner = center_x + side * center_gap
        points = [
            (x_inner, z_back),
            (center_x + side * outer_back, z_back),
            (center_x + side * outer_mid, z_mid),
            (center_x + side * outer_front, z_front),
            (x_inner, z_front),
        ]
        return (
            cq.Workplane("XZ")
            .polyline(points)
            .close()
            .extrude(2.0 * (height_y + 20.0), both=True)
            .val()
        )

    # Work on an explicit copy because transformation behavior differs among
    # CadQuery versions. The translated housing minus the unchanged original
    # gives a two-millimetre surface-conforming layer above the upper shell.
    raised_housing = housing.copy()
    raised_housing = raised_housing.translate((0.0, 2.0, 0.0))
    raised_skin = raised_housing.cut(housing)

    upper_cut_y = hb.ymin + 0.30 * height_y
    upper_slab = cq.Solid.makeBox(
        width_x + 20.0,
        hb.ymax + 7.0 - upper_cut_y,
        length_z + 20.0,
        cq.Vector(hb.xmin - 10.0, upper_cut_y, hb.zmin - 10.0),
    )
    raised_skin = raised_skin.intersect(upper_slab)

    button_solids = []
    creation_modes = []

    for side in (-1, 1):
        footprint = footprint_solid(side)
        raw_button = raised_skin.intersect(footprint)
        candidates = [s for s in raw_button.Solids() if s.Volume() > 0.02]

        if candidates:
            button = max(candidates, key=lambda s: s.Volume())
            creation_modes.append("surface-conforming")
        else:
            # Robust fallback: find the actual upper housing elevation inside
            # this footprint and create a shallow independent pad with 0.1 mm
            # embedded for reliable contact and 2.0 mm exposed height.
            local_housing = housing.intersect(footprint)
            local_parts = list(local_housing.Solids())
            if not local_parts:
                raise ValueError("Button footprint does not overlap the housing")
            local_top = max(p.BoundingBox().ymax for p in local_parts)

            side_center_x = center_x + side * 0.235 * width_x
            pad_dx = 0.245 * width_x
            pad_dz = max(0.16 * length_z, 0.55 * (z_front - z_back))
            pad_center_z = z_back + 0.61 * (z_front - z_back)
            button = cq.Solid.makeBox(
                pad_dx,
                2.1,
                pad_dz,
                cq.Vector(
                    side_center_x - 0.5 * pad_dx,
                    local_top - 0.1,
                    pad_center_z - 0.5 * pad_dz,
                ),
            )
            creation_modes.append("raised-pad fallback")

        # Blend only when the kernel can safely process the imported geometry.
        try:
            radius = min(0.30, 0.04 * min(width_x, length_z))
            button = button.fillet(radius, button.Edges())
        except Exception:
            pass

        button_solids.append(button)

    result = cq.Compound.makeCompound(solids + button_solids)

    print("Input solids:", len(solids))
    print("Housing bbox: X %.3f..%.3f, Y %.3f..%.3f, Z %.3f..%.3f" %
          (hb.xmin, hb.xmax, hb.ymin, hb.ymax, hb.zmin, hb.zmax))
    print("Wheel reference Z: %.3f; center clearance: %.3f" %
          (wheel_z, center_gap))
    print("Button creation modes:", creation_modes)
    print("Added two independent click-button solids with 2.0 mm exposed height")
    print("Output solids:", len(result.Solids()), "Valid:", result.isValid())

    return cq.Workplane(obj=result)