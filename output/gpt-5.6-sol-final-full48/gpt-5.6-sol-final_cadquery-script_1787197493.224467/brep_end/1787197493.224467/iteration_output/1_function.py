def my_cad_function(args):
    import os

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    source_shape = imported.val() if hasattr(imported, "val") else imported
    solids = list(source_shape.Solids())

    print("Imported solids:", len(solids))

    # Identify the main radiator body by its broad Y-Z envelope.
    broad_candidates = []
    for i, solid in enumerate(solids):
        bb = solid.BoundingBox()
        if bb.zlen > 300.0 and bb.ylen > 200.0:
            broad_candidates.append((solid.Volume(), i, solid))

    if broad_candidates:
        broad_candidates.sort(key=lambda item: item[0], reverse=True)
        radiator_index = broad_candidates[0][1]
        radiator = broad_candidates[0][2]
    else:
        radiator_index = max(range(len(solids)), key=lambda i: solids[i].Volume())
        radiator = solids[radiator_index]

    radiator_bb = radiator.BoundingBox()
    tank_top = radiator_bb.ymax
    radiator_z_center = radiator_bb.center.z

    print("Selected radiator solid:", radiator_index)
    print("Upper tank surface y=%.3f" % tank_top)

    # Locate the original top-center service protrusion. Its X coordinate is
    # deliberately retained because it lies on the tank wall rather than at the
    # center of the radiator's total front-to-back envelope.
    service_candidates = []
    for i, solid in enumerate(solids):
        if i == radiator_index:
            continue
        bb = solid.BoundingBox()
        compact = bb.xlen < 70.0 and bb.ylen < 50.0 and bb.zlen < 70.0
        centered_in_height = abs(bb.center.z - radiator_z_center) < 45.0
        attached_above_tank = bb.ymin > tank_top - 3.0 and bb.ymax > tank_top + 3.0
        if compact and centered_in_height and attached_above_tank:
            score = abs(bb.center.z - radiator_z_center) + abs(bb.ymin - tank_top)
            service_candidates.append((score, i, solid))

    removed_indices = set()
    if service_candidates:
        service_candidates.sort(key=lambda item: item[0])
        _, old_service_index, old_service = service_candidates[0]
        old_bb = old_service.BoundingBox()
        filler_x = old_bb.center.x
        filler_z = old_bb.center.z
        removed_indices.add(old_service_index)
        print("Replacing original service fitting solid:", old_service_index)
    else:
        # Conservative fallback near the front-side portion of the upper tank.
        filler_x = radiator_bb.xmin + 0.18 * radiator_bb.xlen
        filler_z = radiator_z_center
        print("No service fitting detected; using inferred tank location.")

    print("Filler axis x=%.3f, z=%.3f" % (filler_x, filler_z))

    axis = cq.Vector(0, 1, 0)
    bore_r = 8.5

    # One-piece stepped pouring neck. All outer stages overlap before the bore
    # is cut, producing a robust annular filler with a reinforced tank root and
    # a defined cap-retaining lip.
    root = cq.Solid.makeCylinder(
        16.5, 7.0,
        cq.Vector(filler_x, tank_top - 3.0, filler_z), axis
    )
    neck = cq.Solid.makeCylinder(
        12.2, 19.0,
        cq.Vector(filler_x, tank_top - 1.0, filler_z), axis
    )
    lip = cq.Solid.makeCylinder(
        15.8, 4.2,
        cq.Vector(filler_x, tank_top + 14.0, filler_z), axis
    )

    neck_blank = root.fuse(neck).fuse(lip)
    neck_bore = cq.Solid.makeCylinder(
        bore_r, 27.0,
        cq.Vector(filler_x, tank_top - 6.0, filler_z), axis
    )
    filler_neck = neck_blank.cut(neck_bore)

    print("Filler neck valid:", filler_neck.isValid())

    # Make a true coaxial passage through the local upper tank wall. Cutting is
    # kept separate from the neck fusion because imported high-detail geometry
    # can reject a combined cut-and-fuse operation even when each part is valid.
    passage = cq.Solid.makeCylinder(
        bore_r, 22.0,
        cq.Vector(filler_x, tank_top - 20.0, filler_z), axis
    )

    edited_radiator = radiator
    try:
        cut_candidate = radiator.cut(passage)
        if cut_candidate.isValid() and len(cut_candidate.Solids()) >= 1:
            edited_radiator = cut_candidate
            print("Upper tank passage cut successfully.")
        else:
            print("Passage cut returned an invalid shape; original tank retained.")
    except Exception as exc:
        print("Passage-cut fallback:", exc)

    # Separate removable cup cap. The bottom recess clears the neck lip while
    # the uncut upper portion closes the opening. A broad lower collar gives the
    # cap a clear hand-grip and distinguishes it from the pouring neck.
    cap_base_y = tank_top + 13.7
    cap_body = cq.Solid.makeCylinder(
        18.3, 12.0,
        cq.Vector(filler_x, cap_base_y, filler_z), axis
    )
    cap_grip = cq.Solid.makeCylinder(
        20.2, 5.0,
        cq.Vector(filler_x, cap_base_y + 0.8, filler_z), axis
    )
    cap_blank = cap_body.fuse(cap_grip)
    cap_recess = cq.Solid.makeCylinder(
        16.4, 9.2,
        cq.Vector(filler_x, cap_base_y - 0.2, filler_z), axis
    )
    cap = cap_blank.cut(cap_recess)

    print("Cap valid:", cap.isValid())

    output_shapes = []
    for i, solid in enumerate(solids):
        if i == radiator_index or i in removed_indices:
            continue
        output_shapes.append(solid)

    output_shapes.append(edited_radiator)
    output_shapes.append(filler_neck)
    output_shapes.append(cap)

    result = cq.Compound.makeCompound(output_shapes)
    print("Removed original fitting solids:", sorted(removed_indices))
    print("Output solids:", len(result.Solids()))
    print("Output valid:", result.isValid())
    return result