def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    lever = cq.importers.importStep(input_file)
    lever_shape = lever.val() if hasattr(lever, "val") else lever
    bbox = lever_shape.BoundingBox()

    print(f"Loaded lever: valid={lever_shape.isValid()}, faces={len(lever_shape.Faces())}")
    print(f"Lever bounds: x=({bbox.xmin:.3f},{bbox.xmax:.3f}), y=({bbox.ymin:.3f},{bbox.ymax:.3f}), z=({bbox.zmin:.3f},{bbox.zmax:.3f})")

    # Locate the two radius-3 transverse bearing surfaces. Their bounding boxes
    # are approximately 6 mm in x and z, and they occur at the negative-x end.
    bearing_faces = []
    for index, face in enumerate(lever_shape.Faces()):
        try:
            if face.geomType() != "CYLINDER":
                continue
            fb = face.BoundingBox()
            radius = float(face.radius())
            cx = 0.5 * (fb.xmin + fb.xmax)
            cz = 0.5 * (fb.zmin + fb.zmax)
            print(f"Cylinder face {index}: r={radius:.4f}, centerXZ=({cx:.4f},{cz:.4f}), y=({fb.ymin:.4f},{fb.ymax:.4f})")
            if abs(radius - 3.0) < 0.15 and cx < bbox.center.x:
                bearing_faces.append((cx, cz, fb.ymin, fb.ymax, face))
        except Exception:
            pass

    if len(bearing_faces) >= 2:
        # Cylinders at the smallest common x coordinate are the clevis bores;
        # positive-x radius-3 cylinders belong to the hook.
        minimum_x = min(item[0] for item in bearing_faces)
        bore_faces = [item for item in bearing_faces if abs(item[0] - minimum_x) < 0.5]
        if len(bore_faces) < 2:
            bore_faces = sorted(bearing_faces, key=lambda item: item[0])[:2]

        pin_x = sum(item[0] for item in bore_faces) / len(bore_faces)
        pin_z = sum(item[1] for item in bore_faces) / len(bore_faces)
        bearing_ymin = min(item[2] for item in bore_faces)
        bearing_ymax = max(item[3] for item in bore_faces)
    else:
        # Dimensions from the supplied feature plan: 7.5 mm lug crown radius
        # and a slot-end plane at x=-60.75 mm place the bore axis here.
        pin_x = -68.25
        pin_z = 0.0
        bearing_ymin = bbox.ymin
        bearing_ymax = bbox.ymax
        print("Bearing-face extraction was inconclusive; using planned bore location.")

    # If cylindrical trimming data does not include both outer cheek faces,
    # use the model's symmetric outer y bounds.
    if bearing_ymax - bearing_ymin < 10.0:
        bearing_ymin = bbox.ymin
        bearing_ymax = bbox.ymax

    end_projection = 1.5
    pin_ymin = bearing_ymin - end_projection
    pin_ymax = bearing_ymax + end_projection
    pin_length = pin_ymax - pin_ymin

    # A 5.8 mm shaft provides 0.1 mm radial running clearance in the nominal
    # 6 mm bore. It remains a separate assembly component so rotation is not
    # prevented by a Boolean union.
    pin_radius = 2.9
    pin = (
        cq.Workplane("XZ", origin=(pin_x, pin_ymin, pin_z))
        .circle(pin_radius)
        .extrude(pin_length)
    )

    # Add equal insertion lead-ins while retaining the full cylindrical
    # bearing surface through both cheeks.
    try:
        pin = pin.edges("%CIRCLE").chamfer(0.35)
    except Exception as exc:
        print(f"Pin-end chamfer skipped: {exc}")

    print(f"Created separate pin: axis=(x={pin_x:.4f}, z={pin_z:.4f}), y=({pin_ymin:.4f},{pin_ymax:.4f}), diameter={2.0 * pin_radius:.3f}")

    result = cq.Assembly(name="clevis_lever_with_rotating_pin")
    result.add(lever_shape, name="tapered_clevis_hook_lever", color=cq.Color(0.27, 0.51, 0.71))
    result.add(pin, name="rotating_cylindrical_pin", color=cq.Color(0.82, 0.82, 0.84))
    return result