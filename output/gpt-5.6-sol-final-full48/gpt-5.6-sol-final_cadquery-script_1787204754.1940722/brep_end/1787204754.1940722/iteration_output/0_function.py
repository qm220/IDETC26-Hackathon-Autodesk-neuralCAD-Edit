def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported
    solids = list(root.Solids())
    if not solids:
        raise ValueError("The input STEP model contains no solids")

    # Identify the broad enclosure solids while ignoring handles, controls,
    # feet, cups, and other comparatively small accessories.
    records = []
    for index, solid in enumerate(solids):
        bb = solid.BoundingBox()
        records.append({
            "index": index,
            "solid": solid,
            "bb": bb,
            "xlen": bb.xmax - bb.xmin,
            "ylen": bb.ymax - bb.ymin,
            "zlen": bb.zmax - bb.zmin,
            "volume": solid.Volume(),
        })

    overall = root.BoundingBox()
    broad = [
        r for r in records
        if r["xlen"] >= 0.70 * (overall.xmax - overall.xmin)
        and r["zlen"] >= 0.55 * (overall.zmax - overall.zmin)
    ]
    if not broad:
        broad = sorted(records, key=lambda r: r["volume"], reverse=True)[:2]

    # The coordinate interpretation supplied with the task establishes -Y as
    # rear and +Z as bottom. Use the largest broad enclosure solid to derive
    # the casing center and width, and all broad enclosure solids to derive the
    # rear and lower casing limits.
    primary = max(broad, key=lambda r: r["volume"])
    body_bb = primary["bb"]
    body_width = body_bb.xmax - body_bb.xmin
    x_center = 0.5 * (body_bb.xmin + body_bb.xmax)
    rear_y = min(r["bb"].ymin for r in broad)
    body_bottom_z = max(r["bb"].zmax for r in broad)

    opening_width = 200.0
    opening_height = 100.0
    corner_radius = 10.0
    pocket_depth = 30.0

    if body_width <= opening_width:
        raise ValueError(
            "The detected rear casing is too narrow for the requested 200 mm opening"
        )

    # Equal left/right margins are guaranteed by centering. Use that nominal
    # side margin as the lower clearance, constrained to a practical range so
    # the lower rail and corner transitions remain intact.
    side_clearance = 0.5 * (body_width - opening_width)
    bottom_clearance = max(15.0, min(side_clearance, 55.0))
    opening_bottom_z = body_bottom_z - bottom_clearance
    z_center = opening_bottom_z - 0.5 * opening_height

    # Build an exact 200 x 100 mm rounded-rectangle prism. The two overlapping
    # boxes form its straight regions and four Y-axis cylinders form the R10
    # corners. Start slightly behind the rear surface to ensure a clean mouth,
    # then extend exactly 30 mm inward from the nominal rear plane.
    lead = 1.0
    cutter_length = pocket_depth + lead
    cutter_y_center = rear_y - lead + 0.5 * cutter_length

    horizontal = (
        cq.Workplane("XY")
        .box(opening_width - 2.0 * corner_radius, cutter_length, opening_height)
        .translate((x_center, cutter_y_center, z_center))
    )
    vertical = (
        cq.Workplane("XY")
        .box(opening_width, cutter_length, opening_height - 2.0 * corner_radius)
        .translate((x_center, cutter_y_center, z_center))
    )
    cutter = horizontal.union(vertical)

    corner_x = 0.5 * opening_width - corner_radius
    corner_z = 0.5 * opening_height - corner_radius
    cylinder_start_y = rear_y - lead
    for dx in (-corner_x, corner_x):
        for dz in (-corner_z, corner_z):
            corner = cq.Solid.makeCylinder(
                corner_radius,
                cutter_length,
                cq.Vector(x_center + dx, cylinder_start_y, z_center + dz),
                cq.Vector(0, 1, 0),
            )
            cutter = cutter.union(cq.Workplane(obj=corner))

    cutter_shape = cutter.val()
    cutter_bb = cutter_shape.BoundingBox()

    # Cut each intersecting solid independently. This preserves the original
    # multi-solid assembly structure and leaves every nonintersecting control,
    # tray, foot, cup, wand, and brew component unchanged.
    output_solids = []
    modified_indices = []
    for record in records:
        bb = record["bb"]
        overlaps = not (
            bb.xmax < cutter_bb.xmin or bb.xmin > cutter_bb.xmax
            or bb.ymax < cutter_bb.ymin or bb.ymin > cutter_bb.ymax
            or bb.zmax < cutter_bb.zmin or bb.zmin > cutter_bb.zmax
        )
        if overlaps:
            cut_result = record["solid"].cut(cutter_shape)
            result_parts = list(cut_result.Solids())
            if result_parts:
                output_solids.extend(result_parts)
                modified_indices.append(record["index"])
            else:
                output_solids.append(record["solid"])
        else:
            output_solids.append(record["solid"])

    result = cq.Compound.makeCompound(output_solids)
    print("Input solids:", len(solids))
    print("Detected body width: %.3f mm" % body_width)
    print("Rear plane Y: %.3f mm" % rear_y)
    print("Body bottom Z: %.3f mm" % body_bottom_z)
    print("Opening center: X=%.3f, Z=%.3f mm" % (x_center, z_center))
    print("Nominal side clearance: %.3f mm" % side_clearance)
    print("Applied bottom clearance: %.3f mm" % bottom_clearance)
    print("Modified solid indices:", modified_indices)
    print("Result valid:", result.isValid())
    return result