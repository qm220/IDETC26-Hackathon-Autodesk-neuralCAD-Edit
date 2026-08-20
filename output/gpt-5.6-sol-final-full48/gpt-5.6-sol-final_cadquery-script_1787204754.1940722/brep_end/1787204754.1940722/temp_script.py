def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported
    solids = list(root.Solids())
    if not solids:
        raise ValueError("The input STEP model contains no solids")

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
    overall_x = overall.xmax - overall.xmin
    overall_y = overall.ymax - overall.ymin

    # In the source coordinates, X is left-right, Y is physical height, and
    # Z is front-back. The plain rear surface is on the minimum-Z side.
    # Select only tall, wide enclosure members so accessories and the lower
    # chassis are not modified.
    enclosure = [
        r for r in records
        if r["xlen"] >= 0.70 * overall_x
        and r["ylen"] >= 0.55 * overall_y
    ]
    if not enclosure:
        enclosure = sorted(records, key=lambda r: r["volume"], reverse=True)[:2]

    primary = max(enclosure, key=lambda r: r["volume"])
    body_bb = primary["bb"]
    body_width = body_bb.xmax - body_bb.xmin
    x_center = 0.5 * (body_bb.xmin + body_bb.xmax)

    rear_z = min(r["bb"].zmin for r in enclosure)
    body_bottom_y = min(r["bb"].ymin for r in enclosure)

    opening_width = 200.0
    opening_height = 100.0
    corner_radius = 10.0
    pocket_depth = 30.0

    if body_width <= opening_width:
        raise ValueError("Detected rear housing is too narrow for a 200 mm opening")

    # Center the feature horizontally. Set its lower clearance approximately
    # equal to the left and right clearances, as requested.
    side_clearance = 0.5 * (body_width - opening_width)
    bottom_clearance = max(15.0, min(side_clearance, 55.0))
    opening_bottom_y = body_bottom_y + bottom_clearance
    y_center = opening_bottom_y + 0.5 * opening_height

    # Construct an exact 200 x 100 mm rounded rectangle with R10 corners and
    # extrude it 30 mm inward from the minimum-Z rear surface. A small lead-in
    # ensures that the pocket mouth cleanly intersects the exterior face.
    lead = 1.0
    cutter_depth = pocket_depth + lead
    cutter_z_center = rear_z - lead + 0.5 * cutter_depth

    horizontal = (
        cq.Workplane("XY")
        .box(opening_width - 2.0 * corner_radius,
             opening_height,
             cutter_depth)
        .translate((x_center, y_center, cutter_z_center))
    )
    vertical = (
        cq.Workplane("XY")
        .box(opening_width,
             opening_height - 2.0 * corner_radius,
             cutter_depth)
        .translate((x_center, y_center, cutter_z_center))
    )
    cutter = horizontal.union(vertical)

    corner_x = 0.5 * opening_width - corner_radius
    corner_y = 0.5 * opening_height - corner_radius
    cylinder_start_z = rear_z - lead
    for dx in (-corner_x, corner_x):
        for dy in (-corner_y, corner_y):
            corner = cq.Solid.makeCylinder(
                corner_radius,
                cutter_depth,
                cq.Vector(x_center + dx, y_center + dy, cylinder_start_z),
                cq.Vector(0, 0, 1),
            )
            cutter = cutter.union(cq.Workplane(obj=corner))

    cutter_shape = cutter.val()
    cutter_bb = cutter_shape.BoundingBox()
    enclosure_indices = {r["index"] for r in enclosure}

    # Restrict the operation to the tall enclosure/rear-cover solids. This
    # preserves the base, feet, tray, cups, controls, wand, and mechanisms.
    output_solids = []
    modified_indices = []
    for record in records:
        bb = record["bb"]
        overlaps = not (
            bb.xmax < cutter_bb.xmin or bb.xmin > cutter_bb.xmax
            or bb.ymax < cutter_bb.ymin or bb.ymin > cutter_bb.ymax
            or bb.zmax < cutter_bb.zmin or bb.zmin > cutter_bb.zmax
        )

        if record["index"] in enclosure_indices and overlaps:
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
    print("Enclosure indices:", sorted(enclosure_indices))
    print("Detected body width: %.3f mm" % body_width)
    print("Rear plane Z: %.3f mm" % rear_z)
    print("Body bottom Y: %.3f mm" % body_bottom_y)
    print("Opening center: X=%.3f, Y=%.3f mm" % (x_center, y_center))
    print("Nominal side clearance: %.3f mm" % side_clearance)
    print("Applied bottom clearance: %.3f mm" % bottom_clearance)
    print("Modified solid indices:", modified_indices)
    print("Result valid:", result.isValid())
    return result