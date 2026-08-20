def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    model = imported.val() if hasattr(imported, "val") else imported

    print(f"Loaded STEP: {input_file}")
    print(f"Model valid: {model.isValid()}")
    print(f"Solid count: {len(model.Solids())}")
    print(f"Face count: {len(model.Faces())}")

    model_bb = model.BoundingBox()
    print(
        "Model bbox: "
        f"x=({model_bb.xmin:.6f}, {model_bb.xmax:.6f}), "
        f"y=({model_bb.ymin:.6f}, {model_bb.ymax:.6f}), "
        f"z=({model_bb.zmin:.6f}, {model_bb.zmax:.6f})"
    )

    bore_candidates = []
    faces = model.Faces()

    # Inspect and print the actual imported topology before creating the pin.
    for index, face in enumerate(faces):
        bb = face.BoundingBox()
        center = face.Center()
        geom_type = face.geomType()
        message = (
            f"FACE {index}: type={geom_type}, area={face.Area():.6f}, "
            f"center=({center.x:.6f},{center.y:.6f},{center.z:.6f}), "
            f"bbox=({bb.xmin:.6f},{bb.ymin:.6f},{bb.zmin:.6f})-"
            f"({bb.xmax:.6f},{bb.ymax:.6f},{bb.zmax:.6f})"
        )

        if geom_type == "CYLINDER":
            try:
                cylinder = face._geomAdaptor().Cylinder()
                radius = cylinder.Radius()
                axis = cylinder.Axis()
                location = axis.Location()
                direction = axis.Direction()
                message += (
                    f", radius={radius:.6f}, "
                    f"axis_location=({location.X():.6f},{location.Y():.6f},{location.Z():.6f}), "
                    f"axis_direction=({direction.X():.6f},{direction.Y():.6f},{direction.Z():.6f})"
                )

                # Geometric binding for F004: radius-3 cylinders parallel to Y,
                # located in the negative-X clevis pivot region.
                if (
                    abs(radius - 3.0) < 0.15
                    and abs(direction.Y()) > 0.99
                    and 0.5 * (bb.xmin + bb.xmax) < -40.0
                ):
                    bore_candidates.append(
                        {
                            "index": index,
                            "face": face,
                            "radius": radius,
                            "x": location.X(),
                            "z": location.Z(),
                            "ymin": bb.ymin,
                            "ymax": bb.ymax,
                        }
                    )
            except Exception as exc:
                message += f", cylinder extraction failed: {exc}"

        print(message)

    if len(bore_candidates) < 2:
        raise ValueError(
            "Could not bind both coaxial clevis bore walls from the imported STEP geometry"
        )

    # Pick the two widest-separated bore-wall segments, corresponding to the
    # negative-Y and positive-Y ears, then verify their common axis.
    bore_candidates.sort(key=lambda item: 0.5 * (item["ymin"] + item["ymax"]))
    negative_bore = bore_candidates[0]
    positive_bore = bore_candidates[-1]

    axis_x = 0.5 * (negative_bore["x"] + positive_bore["x"])
    axis_z = 0.5 * (negative_bore["z"] + positive_bore["z"])
    coaxial_error = (
        (negative_bore["x"] - positive_bore["x"]) ** 2
        + (negative_bore["z"] - positive_bore["z"]) ** 2
    ) ** 0.5

    if coaxial_error > 0.05:
        raise ValueError(
            f"Selected bore walls are not coaxial; axis offset is {coaxial_error:.6f} mm"
        )

    pin_ymin = min(negative_bore["ymin"], positive_bore["ymin"])
    pin_ymax = max(negative_bore["ymax"], positive_bore["ymax"])
    pin_length = pin_ymax - pin_ymin

    nominal_bore_radius = 0.5 * (
        negative_bore["radius"] + positive_bore["radius"]
    )
    radial_clearance = 0.05
    pin_radius = nominal_bore_radius - radial_clearance
    chamfer_size = 0.30

    print(
        f"Bound F004 to FACE {negative_bore['index']} and FACE {positive_bore['index']}"
    )
    print(
        f"Common pivot axis: origin=({axis_x:.6f},0.000000,{axis_z:.6f}), "
        "direction=(0,1,0)"
    )
    print(f"Coaxial verification error: {coaxial_error:.9f} mm")
    print(
        f"Creating separate pin: diameter={2.0 * pin_radius:.6f} mm, "
        f"length={pin_length:.6f} mm, y=({pin_ymin:.6f},{pin_ymax:.6f}), "
        f"radial clearance={radial_clearance:.6f} mm"
    )

    pin_solid = cq.Solid.makeCylinder(
        pin_radius,
        pin_length,
        cq.Vector(axis_x, pin_ymin, axis_z),
        cq.Vector(0, 1, 0),
    )

    # Add equal insertion lead-ins to both circular end edges while preserving
    # the full-diameter bearing region through both clevis ears.
    try:
        pin = cq.Workplane(obj=pin_solid).edges("%Circle").chamfer(chamfer_size).val()
        print(f"Applied {chamfer_size:.3f} mm chamfers to both pin ends")
    except Exception as exc:
        print(f"Pin chamfer failed; retaining the valid cylindrical pin: {exc}")
        pin = pin_solid

    if not pin.isValid():
        raise ValueError("Generated pin is not a valid solid")

    # An assembly preserves the pin and original lever as distinct bodies,
    # allowing rotational motion about their shared Y axis.
    result = cq.Assembly(name="lever_with_pivot_pin")
    result.add(model, name="hook_ended_clevis_lever", color=cq.Color(0.72, 0.72, 0.76))
    result.add(pin, name="clearance_fit_pivot_pin", color=cq.Color(0.82, 0.58, 0.18))

    print("Created assembly with the original lever and one separate pivot-pin solid")
    return result