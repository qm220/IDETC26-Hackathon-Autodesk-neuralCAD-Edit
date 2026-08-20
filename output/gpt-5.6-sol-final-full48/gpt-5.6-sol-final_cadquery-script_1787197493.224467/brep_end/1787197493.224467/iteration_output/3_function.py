def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    source_shape = imported.val() if hasattr(imported, "val") else imported
    solids = list(source_shape.Solids())

    print("Imported solids:", len(solids))
    print("Imported shape valid:", source_shape.isValid())

    # Identify the broad radiator body while preserving fans, guards, ports,
    # mounts, and all other accessory solids.
    broad_candidates = []
    for i, solid in enumerate(solids):
        bb = solid.BoundingBox()
        if bb.ylen > 200.0 and bb.zlen > 300.0:
            broad_candidates.append((abs(solid.Volume()), i, solid))

    if broad_candidates:
        broad_candidates.sort(key=lambda item: item[0], reverse=True)
        _, radiator_index, radiator = broad_candidates[0]
    else:
        radiator_index = max(range(len(solids)), key=lambda i: abs(solids[i].Volume()))
        radiator = solids[radiator_index]

    radiator_bb = radiator.BoundingBox()
    tank_top = radiator_bb.ymax
    radiator_z_center = radiator_bb.center.z

    print("Selected radiator solid:", radiator_index)
    print("Radiator valid before edit:", radiator.isValid())
    print("Upper tank surface y=%.3f" % tank_top)

    # Locate and replace the compact original top-center service protrusion.
    service_candidates = []
    for i, solid in enumerate(solids):
        if i == radiator_index:
            continue
        bb = solid.BoundingBox()
        compact = bb.xlen < 70.0 and bb.ylen < 55.0 and bb.zlen < 70.0
        centered = abs(bb.center.z - radiator_z_center) < 45.0
        top_mounted = bb.ymin > tank_top - 5.0 and bb.ymax > tank_top + 2.0
        if compact and centered and top_mounted:
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
        print("Original top feature not detected; using inferred position.")

    print("Filler axis x=%.3f, z=%.3f" % (filler_x, filler_z))

    axis = cq.Vector(0, 1, 0)

    def axis_point(y):
        return cq.Vector(filler_x, y, filler_z)

    # Functional pouring neck: an embedded mounting boss, raised tubular neck,
    # cap seat, and retaining lip. A continuous axial bore runs below the tank
    # surface and through every neck stage.
    bore_r = 9.0
    root = cq.Solid.makeCylinder(17.0, 8.0, axis_point(tank_top - 4.0), axis)
    lower_neck = cq.Solid.makeCylinder(13.0, 15.5, axis_point(tank_top - 1.0), axis)
    cap_seat = cq.Solid.makeCylinder(14.5, 7.0, axis_point(tank_top + 11.5), axis)
    retaining_lip = cq.Solid.makeCylinder(16.2, 4.0, axis_point(tank_top + 16.0), axis)

    neck_blank = root.fuse(lower_neck).fuse(cap_seat).fuse(retaining_lip)
    neck_bore = cq.Solid.makeCylinder(9.0, 38.0, axis_point(tank_top - 12.0), axis)
    filler_neck = neck_blank.cut(neck_bore)
    try:
        filler_neck = filler_neck.clean()
    except Exception:
        pass
    print("Filler neck valid:", filler_neck.isValid())

    # Cut the coaxial passage into the upper radiator tank. Imported topology is
    # already reported invalid, so success is assessed by a real volume change
    # and retained solids rather than requiring the result to become globally
    # valid. This avoids rejecting a successful local cut solely because of an
    # unrelated defect elsewhere in the imported radiator body.
    passage = cq.Solid.makeCylinder(
        bore_r, 24.0, axis_point(tank_top - 18.0), axis
    )
    edited_radiator = radiator
    passage_cut = False
    original_volume = abs(radiator.Volume())

    try:
        candidate = radiator.cut(passage)
        candidate_solids = list(candidate.Solids())
        candidate_volume = abs(candidate.Volume())
        volume_removed = original_volume - candidate_volume
        print("Direct cut volume removed:", volume_removed)
        if candidate_solids and volume_removed > 0.1:
            edited_radiator = candidate
            passage_cut = True
            print("Upper-tank passage accepted from CadQuery boolean.")
    except Exception as exc:
        print("CadQuery passage cut failed:", exc)

    # Retry with a fuzzy OCCT boolean and the required TopTools shape lists.
    if not passage_cut:
        try:
            from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
            from OCP.TopTools import TopTools_ListOfShape

            arguments = TopTools_ListOfShape()
            tools = TopTools_ListOfShape()
            arguments.Append(radiator.wrapped)
            tools.Append(passage.wrapped)

            cutter = BRepAlgoAPI_Cut()
            cutter.SetArguments(arguments)
            cutter.SetTools(tools)
            cutter.SetFuzzyValue(1.0e-3)
            cutter.SetNonDestructive(True)
            cutter.Build()

            if cutter.IsDone():
                candidate = cq.Shape.cast(cutter.Shape())
                candidate_solids = list(candidate.Solids())
                candidate_volume = abs(candidate.Volume())
                volume_removed = original_volume - candidate_volume
                print("Fuzzy cut volume removed:", volume_removed)
                if candidate_solids and volume_removed > 0.1:
                    edited_radiator = candidate
                    passage_cut = True
                    print("Upper-tank passage accepted from fuzzy OCCT boolean.")
        except Exception as exc:
            print("Fuzzy passage cut failed:", exc)

    # Distinct removable pressure-cap form. Its annular skirt clears and
    # surrounds the retaining lip, while the uncut upper web closes the bore.
    cap_base_y = tank_top + 16.35
    cap_skirt = cq.Solid.makeCylinder(18.4, 10.5, axis_point(cap_base_y), axis)
    cap_crown = cq.Solid.makeCylinder(20.5, 4.0, axis_point(cap_base_y + 7.0), axis)
    cap_blank = cap_skirt.fuse(cap_crown)

    cap_recess = cq.Solid.makeCylinder(
        16.7, 7.7, axis_point(cap_base_y - 0.2), axis
    )
    cap = cap_blank.cut(cap_recess)

    # Opposed ears provide a clear hand-grip and identify the cap as removable.
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

    # Reassemble without changing the fans, guards, blades, hubs, hose ports,
    # frame details, or corner mounts. Only the original service protrusion is
    # replaced and the radiator receives the localized passage when successful.
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