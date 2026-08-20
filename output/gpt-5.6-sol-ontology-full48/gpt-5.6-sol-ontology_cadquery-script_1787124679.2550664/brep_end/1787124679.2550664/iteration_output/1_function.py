def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    model = imported.val() if hasattr(imported, "val") else imported
    solids = list(model.Solids())
    faces = list(model.Faces())

    print(f"Loaded model: valid={model.isValid()}, solids={len(solids)}, faces={len(faces)}")
    if len(solids) <= 17:
        raise ValueError("Expected SOLID 0 housing and SOLID 17 cradle were not found")

    # Bind the planned targets to the imported STEP geometry.
    housing = solids[0]
    cradle = solids[17]
    for idx, name in [(41, "housing lower wall"), (361, "right cradle bore"),
                      (362, "left cradle bore"), (365, "cradle outer wall"),
                      (366, "cradle inner wall")]:
        face = faces[idx]
        bb = face.BoundingBox()
        c = face.Center()
        print(
            f"FACE {idx} ({name}): type={face.geomType()}, "
            f"center=({c.x:.6f},{c.y:.6f},{c.z:.6f}), "
            f"bbox=({bb.xmin:.6f},{bb.ymin:.6f},{bb.zmin:.6f}) to "
            f"({bb.xmax:.6f},{bb.ymax:.6f},{bb.zmax:.6f})"
        )

    hbb = housing.BoundingBox()
    cbb = cradle.BoundingBox()
    print(
        f"Housing bbox=({hbb.xmin:.6f},{hbb.ymin:.6f},{hbb.zmin:.6f}) to "
        f"({hbb.xmax:.6f},{hbb.ymax:.6f},{hbb.zmax:.6f})"
    )
    print(
        f"Original cradle bbox=({cbb.xmin:.6f},{cbb.ymin:.6f},{cbb.zmin:.6f}) to "
        f"({cbb.xmax:.6f},{cbb.ymax:.6f},{cbb.zmax:.6f})"
    )

    # FACE 366 follows the same lower profile as housing FACE 41, so the source
    # parts have coincident/tangent geometry even though their common volume is
    # numerically zero. Enlarge the housing envelope by 2.5 percent and use it
    # as a clearance cutter. Since the housing is centered at x=z=0 and starts
    # at y=0, uniform scaling about the global origin expands the complete X-Z
    # envelope and also fully covers the cradle's Y span.
    clearance_scale = 1.025
    clearance_cutter = housing.scale(clearance_scale)
    revised_cradle = cradle.cut(clearance_cutter)

    if revised_cradle is None or revised_cradle.isNull():
        raise RuntimeError("Clearance cut produced a null cradle")
    if not revised_cradle.isValid():
        raise RuntimeError("Clearance cut produced an invalid cradle")

    revised_parts = []
    for i, solid in enumerate(solids):
        if i == 17:
            revised_parts.extend(list(revised_cradle.Solids()))
        else:
            revised_parts.append(solid)

    result = cq.Compound.makeCompound(revised_parts)
    if not result.isValid():
        raise RuntimeError("Edited assembly compound is invalid")

    common = housing.intersect(revised_cradle)
    common_volume = 0.0 if common is None or common.isNull() else common.Volume()
    print(f"Final housing/cradle common volume: {common_volume:.12f} mm^3")
    print(f"Revised cradle solids: {len(revised_cradle.Solids())}")
    print(f"Output assembly solids: {len(result.Solids())}")

    # Confirm that the retained cylindrical bore portions preserve their axes
    # and nominal 7.62 mm radii. The inner ends may be shortened by the new gap.
    bore_candidates = []
    for face in revised_cradle.Faces():
        if face.geomType() == "CYLINDER":
            bb = face.BoundingBox()
            if bb.xmax > 100.0 or bb.xmin < -100.0:
                bore_candidates.append(face)
    print(f"Retained cradle cylindrical bore-face candidates: {len(bore_candidates)}")
    for i, face in enumerate(bore_candidates):
        bb = face.BoundingBox()
        c = face.Center()
        print(
            f"Revised bore candidate {i}: center=({c.x:.6f},{c.y:.6f},{c.z:.6f}), "
            f"bbox=({bb.xmin:.6f},{bb.ymin:.6f},{bb.zmin:.6f}) to "
            f"({bb.xmax:.6f},{bb.ymax:.6f},{bb.zmax:.6f})"
        )

    return cq.Workplane("XY").newObject([result])