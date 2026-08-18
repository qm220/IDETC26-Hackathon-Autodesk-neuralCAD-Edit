def my_cad_function(args):
    import os
    import math

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    source_shape = imported.val() if hasattr(imported, "val") else imported
    source_bbox = source_shape.BoundingBox()

    print(f"Imported radiator valid: {source_shape.isValid()}")
    print(f"Imported bounding box: x=({source_bbox.xmin:.3f},{source_bbox.xmax:.3f}), y=({source_bbox.ymin:.3f},{source_bbox.ymax:.3f}), z=({source_bbox.zmin:.3f},{source_bbox.zmax:.3f})")

    # Inspect disconnected solids and locate the compact existing service-cap
    # body nearest the top longitudinal center of the radiator.
    solids = list(source_shape.Solids())
    print(f"Detected disconnected solids: {len(solids)}")
    cap_candidate = None
    cap_score = 1.0e99

    for index, solid in enumerate(solids):
        bb = solid.BoundingBox()
        center = bb.center
        print(
            f"Solid {index}: center=({center.x:.3f},{center.y:.3f},{center.z:.3f}), "
            f"size=({bb.xlen:.3f},{bb.ylen:.3f},{bb.zlen:.3f})"
        )
        compact = bb.xlen < 100.0 and bb.ylen < 80.0 and bb.zlen < 100.0
        top_centered = center.y > 165.0 and abs(center.z) < 55.0
        if compact and top_centered:
            score = abs(center.z) + 0.12 * abs(center.y - 181.4) + 0.01 * (bb.xlen + bb.zlen)
            if score < cap_score:
                cap_score = score
                cap_candidate = solid

    # The known top-tank wall is y=174.851756 mm. Determine the filler x-axis
    # position from the existing cap when possible, otherwise use the center of
    # the radiator tank depth reported by the source geometry.
    top_wall_y = 174.851756
    filler_z = 0.0
    filler_x = -87.30
    if cap_candidate is not None:
        cap_bb = cap_candidate.BoundingBox()
        filler_x = cap_bb.center.x
        print(f"Existing service cap selected at x={filler_x:.3f}, y={cap_bb.center.y:.3f}, z={cap_bb.center.z:.3f}")
    else:
        print("Existing service cap was not isolated as a solid; using the top-tank depth center x=-87.30 mm.")

    # Remove the simplified original cap body so it can be replaced by a
    # detailed, removable cap. Preserve every other source component.
    kept_solids = []
    for solid in solids:
        if cap_candidate is None or not solid.isSame(cap_candidate):
            kept_solids.append(solid)

    if kept_solids:
        base_shape = cq.Compound.makeCompound(kept_solids)
    else:
        base_shape = source_shape

    axis_y = cq.Vector(0, 1, 0)

    def cylinder(radius, height, y0, x0=filler_x, z0=filler_z):
        return cq.Solid.makeCylinder(radius, height, cq.Vector(x0, y0, z0), axis_y)

    def cone(radius1, radius2, height, y0, x0=filler_x, z0=filler_z):
        return cq.Solid.makeCone(radius1, radius2, height, cq.Vector(x0, y0, z0), axis_y)

    # Cut a true coolant opening through the upper tank wall. The cut is kept
    # narrowly localized and stops below the top rail without approaching the
    # radiator core field.
    tank_opening = cylinder(13.0, 18.0, 164.0)
    try:
        edited_base = base_shape.cut(tank_opening)
        if edited_base is None or edited_base.isNull():
            edited_base = base_shape
            print("Tank opening cut returned a null shape; preserved source radiator.")
        else:
            print("Created coolant passage through the top tank wall.")
    except Exception as exc:
        edited_base = base_shape
        print(f"Top-tank cut could not be applied to the invalid imported compound: {exc}")

    # Integral pouring neck: embedded reinforcing collar, pressure-wall tube,
    # flared pouring mouth, rounded thread bands, and a sealing land.
    root_outer = cylinder(25.0, 9.0, 171.5)
    root_inner = cylinder(13.0, 11.0, 170.5)
    root_annulus = root_outer.cut(root_inner)

    tube_outer = cylinder(20.0, 31.0, top_wall_y)
    tube_inner = cylinder(13.0, 33.0, top_wall_y - 1.0)
    tube_annulus = tube_outer.cut(tube_inner)

    flare_outer = cone(20.0, 24.0, 10.0, 202.0)
    flare_inner = cone(13.0, 17.0, 11.0, 201.5)
    flare_annulus = flare_outer.cut(flare_inner)

    neck = root_annulus.fuse(tube_annulus).fuse(flare_annulus)

    # Simplified external retention thread represented by three robust annular
    # thread bands. This conveys the removable threaded interface without using
    # a fragile helical boolean on the imported invalid assembly.
    for thread_y in (190.0, 195.0, 200.0):
        thread_outer = cylinder(22.2, 1.8, thread_y)
        thread_inner = cylinder(19.7, 2.2, thread_y - 0.2)
        neck = neck.fuse(thread_outer.cut(thread_inner))

    # Raised axial gasket land immediately below the pouring lip.
    land_outer = cylinder(21.3, 2.0, 203.0)
    land_inner = cylinder(13.0, 2.4, 202.8)
    neck = neck.fuse(land_outer.cut(land_inner))

    # Removable hollow cap, coaxial with the pouring neck. Its internal cavity
    # clears the retention bands, while the closed crown provides the pressure
    # boundary and the flared exterior provides a hand-operated grip.
    skirt = cylinder(27.5, 17.0, 203.5)
    grip_flare = cone(27.5, 31.0, 6.0, 220.5)
    crown = cone(31.0, 23.0, 5.5, 226.5)
    cap = skirt.fuse(grip_flare).fuse(crown)

    cap_cavity = cylinder(24.3, 23.5, 202.5)
    cap = cap.cut(cap_cavity)

    # Twelve rounded axial grip ribs around the cap perimeter.
    grip_radius = 29.0
    for i in range(12):
        angle = 2.0 * math.pi * i / 12.0
        rib_x = filler_x + grip_radius * math.cos(angle)
        rib_z = filler_z + grip_radius * math.sin(angle)
        rib = cylinder(3.2, 15.0, 211.0, rib_x, rib_z)
        cap = cap.fuse(rib)

    # Captive elastomeric gasket shown as a separate annular component at the
    # axial sealing plane. It fits inside the cap and seats on the neck land.
    gasket_outer = cylinder(22.8, 2.2, 210.6)
    gasket_inner = cylinder(17.2, 2.6, 210.4)
    gasket = gasket_outer.cut(gasket_inner)

    print(
        f"Filling system created on axis x={filler_x:.3f}, z={filler_z:.3f}: "
        "26 mm coolant bore, reinforced flared pouring neck, threaded retention bands, gasket, and removable ribbed cap."
    )

    result = cq.Assembly(name="radiator_with_filling_system")
    result.add(edited_base, name="radiator_existing", color=cq.Color(0.35, 0.35, 0.38))
    result.add(neck, name="integral_pouring_neck", color=cq.Color(0.72, 0.72, 0.76))
    result.add(gasket, name="cap_gasket", color=cq.Color(0.12, 0.12, 0.12))
    result.add(cap, name="removable_fill_cap", color=cq.Color(0.55, 0.22, 0.68))
    return result