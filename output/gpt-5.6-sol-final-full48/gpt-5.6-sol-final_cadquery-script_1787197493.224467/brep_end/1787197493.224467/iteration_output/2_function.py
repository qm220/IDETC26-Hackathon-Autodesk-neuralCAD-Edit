def my_cad_function(args):
    import os

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    source_shape = imported.val() if hasattr(imported, "val") else imported
    solids = list(source_shape.Solids())

    print("Imported solids:", len(solids))
    print("Imported shape valid:", source_shape.isValid())

    # Select the broad radiator/core body while preserving all accessory solids.
    broad_candidates = []
    for i, solid in enumerate(solids):
        bb = solid.BoundingBox()
        if bb.ylen > 200.0 and bb.zlen > 300.0:
            broad_candidates.append((solid.Volume(), i, solid))

    if broad_candidates:
        broad_candidates.sort(key=lambda item: item[0], reverse=True)
        _, radiator_index, radiator = broad_candidates[0]
    else:
        radiator_index = max(range(len(solids)), key=lambda i: solids[i].Volume())
        radiator = solids[radiator_index]

    radiator_bb = radiator.BoundingBox()
    tank_top = radiator_bb.ymax
    radiator_z_center = radiator_bb.center.z

    print("Selected radiator solid:", radiator_index)
    print("Radiator valid before edit:", radiator.isValid())
    print("Upper tank surface y=%.3f" % tank_top)

    # Find the compact existing top-center service feature. Its original X and
    # Z coordinates define the intended filler location on the upper tank.
    service_candidates = []
    for i, solid in enumerate(solids):
        if i == radiator_index:
            continue
        bb = solid.BoundingBox()
        compact = bb.xlen < 70.0 and bb.ylen < 55.0 and bb.zlen < 70.0
        near_center = abs(bb.center.z - radiator_z_center) < 45.0
        on_upper_tank = bb.ymin > tank_top - 5.0 and bb.ymax > tank_top + 2.0
        if compact and near_center and on_upper_tank:
            score = abs(bb.center.z - radiator_z_center) + abs(bb.ymin - tank_top)
            service_candidates.append((score, i, solid))

    removed_indices = set()
    if service_candidates:
        service_candidates.sort(key=lambda item: item[0])
        _, service_index, service_solid = service_candidates[0]
        service_bb = service_solid.BoundingBox()
        filler_x = service_bb.center.x
        filler_z = service_bb.center.z
        removed_indices.add(service_index)
        print("Replacing original top service feature:", service_index)
    else:
        filler_x = radiator_bb.xmin + 0.18 * radiator_bb.xlen
        filler_z = radiator_z_center
        print("Top service feature not detected; using inferred location.")

    print("Filler axis x=%.3f, z=%.3f" % (filler_x, filler_z))

    axis = cq.Vector(0, 1, 0)
    axis_point = lambda y: cq.Vector(filler_x, y, filler_z)

    # Raised pouring neck. Overlapping stages are fused before the continuous
    # axial bore is cut. The wide root is embedded into the upper tank, the
    # middle section guides pouring, and the upper flange supports the cap.
    bore_r = 9.0
    root = cq.Solid.makeCylinder(17.0, 7.5, axis_point(tank_top - 3.5), axis)
    lower_neck = cq.Solid.makeCylinder(13.0, 15.5, axis_point(tank_top - 1.0), axis)
    upper_neck = cq.Solid.makeCylinder(14.2, 8.0, axis_point(tank_top + 11.5), axis)
    retaining_lip = cq.Solid.makeCylinder(16.2, 4.0, axis_point(tank_top + 16.0), axis)

    neck_blank = root.fuse(lower_neck).fuse(upper_neck).fuse(retaining_lip)
    neck_bore = cq.Solid.makeCylinder(
        bore_r, 33.0, axis_point(tank_top - 8.0), axis
    )
    filler_neck = neck_blank.cut(neck_bore)
    try:
        filler_neck = filler_neck.clean()
    except Exception:
        pass

    print("Filler neck valid:", filler_neck.isValid())

    # Attempt a real coaxial passage through the local upper-tank wall. First
    # use CadQuery's boolean operation, then retry with OCCT's fuzzy boolean for
    # imported topology. The original radiator is retained if neither produces
    # a usable result.
    passage = cq.Solid.makeCylinder(
        bore_r, 18.0, axis_point(tank_top - 15.0), axis
    )
    edited_radiator = radiator
    passage_cut = False

    try:
        candidate = radiator.cut(passage)
        try:
            candidate = candidate.clean()
        except Exception:
            pass
        if candidate.isValid() and len(candidate.Solids()) >= 1:
            edited_radiator = candidate
            passage_cut = True
            print("Upper-tank passage cut with CadQuery boolean.")
    except Exception as exc:
        print("CadQuery passage cut failed:", exc)

    if not passage_cut:
        try:
            from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
            cutter = BRepAlgoAPI_Cut()
            cutter.SetArguments([radiator.wrapped])
            cutter.SetTools([passage.wrapped])
            cutter.SetFuzzyValue(1.0e-4)
            cutter.SetNonDestructive(True)
            cutter.Build()
            if cutter.IsDone():
                candidate = cq.Shape.cast(cutter.Shape())
                if candidate.isValid() and len(candidate.Solids()) >= 1:
                    edited_radiator = candidate
                    passage_cut = True
                    print("Upper-tank passage cut with fuzzy OCCT boolean.")
        except Exception as exc:
            print("Fuzzy passage cut failed:", exc)

    if not passage_cut:
        print("Imported tank topology rejected the passage cut; hollow neck retained as a representational fluid interface.")

    # Separate removable pressure-cap form. The lower recess clears the neck
    # retaining lip, while the closed upper web seals the bore. Two opposing
    # grip ears make the cap visually and mechanically distinct from the neck.
    cap_base_y = tank_top + 16.35
    cap_body = cq.Solid.makeCylinder(18.4, 10.5, axis_point(cap_base_y), axis)
    cap_top = cq.Solid.makeCylinder(20.5, 4.0, axis_point(cap_base_y + 7.0), axis)
    cap_blank = cap_body.fuse(cap_top)

    cap_recess = cq.Solid.makeCylinder(
        16.7, 7.7, axis_point(cap_base_y - 0.2), axis
    )
    cap = cap_blank.cut(cap_recess)

    # Opposed turning lugs on the closed top of the cap.
    lug_y = cap_base_y + 8.0
    lug1 = cq.Solid.makeBox(
        13.0, 3.0, 8.0,
        cq.Vector(filler_x + 15.5, lug_y, filler_z - 4.0)
    )
    lug2 = cq.Solid.makeBox(
        13.0, 3.0, 8.0,
        cq.Vector(filler_x - 28.5, lug_y, filler_z - 4.0)
    )
    cap = cap.fuse(lug1).fuse(lug2)
    try:
        cap = cap.clean()
    except Exception:
        pass

    print("Cap valid:", cap.isValid())

    # Rebuild the assembly, replacing only the original top-center fitting and
    # the radiator solid if its passage cut succeeded. Fans, guards, hose
    # connections, mounts, core, and frame remain untouched.
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
    print("Passage created:", passage_cut)
    print("Output solids:", len(result.Solids()))
    print("Output valid:", result.isValid())
    return result