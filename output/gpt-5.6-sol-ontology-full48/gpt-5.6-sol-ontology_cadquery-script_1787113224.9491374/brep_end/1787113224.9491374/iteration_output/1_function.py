def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    faces = shape.Faces()
    print("Loaded original STEP model for reinforcing-rib operation")
    print(f"Original valid={shape.isValid()}, solids={len(shape.Solids())}, faces={len(faces)}, volume={shape.Volume():.6f}")

    # Confirm the deterministic STEP bindings used to place and constrain the rib.
    for index, label in ((77, "principal underside mounting plane"),
                         (107, "curved relief-cavity roof/wall"),
                         (44, "first clevis bore"),
                         (46, "second clevis bore")):
        face = faces[index]
        c = face.Center()
        b = face.BoundingBox()
        print(
            f"FACE {index} ({label}): {face.geomType()} "
            f"center=({c.x:.6f},{c.y:.6f},{c.z:.6f}) "
            f"bbox=x({b.xmin:.6f},{b.xmax:.6f}) "
            f"y({b.ymin:.6f},{b.ymax:.6f}) "
            f"z({b.zmin:.6f},{b.zmax:.6f})"
        )

    # FACE 77 establishes y=-0.010 mm as the lowest permissible plane.
    underside_y = faces[77].BoundingBox().ymin

    # Add one longitudinal vertical web inside the underside relief. Its principal
    # span follows CAD X, from one surrounding cavity wall to the other. The exact
    # requested 1.5 mm thickness is along CAD Z. The negative-Z location follows
    # the grounded cavity roof represented by FACE 107 and remains remote from the
    # clevis gap/bore at z=2.943 and from all four end mounting holes.
    rib_thickness = 1.5
    rib_z_min = -2.60

    # XY side profile. The lower edge terminates exactly at the mounting plane and
    # overlaps the existing base skin. The shaped upper edge penetrates slightly
    # into the cavity roof and surrounding web so the resulting rib is integral.
    rib_profile = [
        (2.15, underside_y),
        (10.20, underside_y),
        (10.20, 2.35),
        (9.30, 2.85),
        (7.20, 3.35),
        (4.70, 3.40),
        (3.00, 3.05),
        (2.15, 2.65)
    ]

    rib = (
        cq.Workplane("XY", origin=(0.0, 0.0, rib_z_min))
        .polyline(rib_profile)
        .close()
        .extrude(rib_thickness)
    )

    result = cq.Workplane(obj=shape).union(rib, clean=True)
    result_shape = result.val()

    # Preserve the four mounting interfaces explicitly. These cutters are remote
    # from the new rib but guarantee that no boolean overlap can obstruct a bore.
    mounting_centers = [
        (0.293627, -1.526470),
        (0.293627, 1.473530),
        (11.953627, 1.123530),
        (11.953627, -2.986470)
    ]
    for x, z in mounting_centers:
        cutter = (
            cq.Workplane("XZ", origin=(0.0, -0.50, 0.0))
            .center(x, z)
            .circle(0.400000)
            .extrude(6.0)
        )
        result = result.cut(cutter)

    # Preserve the coaxial clevis pin bore through both ears and the central gap.
    pin_cutter = (
        cq.Workplane("YZ", origin=(4.40, 0.0, 0.0))
        .center(3.510000, 2.943179)
        .circle(0.750000)
        .extrude(3.50)
    )
    result = result.cut(pin_cutter).clean()
    result_shape = result.val()
    rb = result_shape.BoundingBox()

    print(f"Rib thickness: {rib_thickness:.6f} mm along CAD Z")
    print(f"Rib z extent: ({rib_z_min:.6f}, {rib_z_min + rib_thickness:.6f})")
    print(f"Rib lower termination y={underside_y:.6f} mm (FACE 77 plane)")
    print(
        f"Result valid={result_shape.isValid()}, solids={len(result_shape.Solids())}, "
        f"faces={len(result_shape.Faces())}, volume={result_shape.Volume():.6f}"
    )
    print(
        f"Result bbox=x({rb.xmin:.6f},{rb.xmax:.6f}) "
        f"y({rb.ymin:.6f},{rb.ymax:.6f}) "
        f"z({rb.zmin:.6f},{rb.zmax:.6f})"
    )

    if not result_shape.isValid():
        raise ValueError("The rib addition produced an invalid B-rep")
    if len(result_shape.Solids()) != 1:
        raise ValueError("The reinforcing rib is not integral with the original bracket")
    if rb.ymin < underside_y - 1.0e-5:
        raise ValueError("The reinforcing rib protrudes below FACE 77")

    return result