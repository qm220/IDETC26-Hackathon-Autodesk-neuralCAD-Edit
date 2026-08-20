def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported
    solids = list(root.Solids())

    print(f"Loaded STEP: {input_file}")
    print(f"Root valid={root.isValid()}, solids={len(solids)}, faces={len(root.Faces())}")

    # Bind R04 / SOLID 3 to geometry rather than relying on STEP solid ordering.
    # The heat break is the slender solid centered near (0,-40), with z≈0.4..21.
    target_index = None
    best_score = 1.0e99
    for i, solid in enumerate(solids):
        bb = solid.BoundingBox()
        c = bb.center
        print(
            f"SOLID {i}: center=({c.x:.4f},{c.y:.4f},{c.z:.4f}) "
            f"bbox=({bb.xmin:.4f},{bb.ymin:.4f},{bb.zmin:.4f}).."
            f"({bb.xmax:.4f},{bb.ymax:.4f},{bb.zmax:.4f}) "
            f"size=({bb.xlen:.4f},{bb.ylen:.4f},{bb.zlen:.4f})"
        )
        score = (
            (c.x - 0.0) ** 2
            + (c.y + 40.0) ** 2
            + 0.2 * (c.z - 10.7) ** 2
            + 20.0 * abs(bb.zlen - 20.6)
        )
        if bb.xlen < 10.0 and bb.ylen < 10.0 and 18.0 < bb.zlen < 24.0 and score < best_score:
            best_score = score
            target_index = i

    if target_index is None:
        raise RuntimeError("Could not geometrically identify the R04 tubular heat-break solid")

    heatbreak = solids[target_index]
    print(f"Bound R04 tubular heat break to actual solid index {target_index}")

    # Inspect and bind F014 / planned FACE 749 by its actual geometry.
    sleeve_face = None
    sleeve_score = 1.0e99
    for i, face in enumerate(heatbreak.Faces()):
        bb = face.BoundingBox()
        c = bb.center
        gt = face.geomType()
        print(
            f"R04 FACE {i}: type={gt}, area={face.Area():.6f}, "
            f"center=({c.x:.4f},{c.y:.4f},{c.z:.4f}), "
            f"bbox=({bb.xmin:.4f},{bb.ymin:.4f},{bb.zmin:.4f}).."
            f"({bb.xmax:.4f},{bb.ymax:.4f},{bb.zmax:.4f})"
        )
        if gt == "CYLINDER":
            # Expected main sleeve: radius 3.45, z=7.5..20.8, axis along Z.
            radius_est = 0.25 * (bb.xlen + bb.ylen)
            score = (
                20.0 * abs(radius_est - 3.45)
                + abs(bb.zmin - 7.5)
                + abs(bb.zmax - 20.8)
                + abs(c.x)
                + abs(c.y + 40.0)
            )
            if bb.zlen > 10.0 and score < sleeve_score:
                sleeve_score = score
                sleeve_face = face

    if sleeve_face is None:
        raise RuntimeError("Could not bind F014 main radius-3.45 outer sleeve face")

    sbb = sleeve_face.BoundingBox()
    sleeve_radius = 0.25 * (sbb.xlen + sbb.ylen)
    lower_z = sbb.zmin
    upper_z = sbb.zmax
    print(
        f"Bound F014 main sleeve: estimated radius={sleeve_radius:.6f}, "
        f"z={lower_z:.6f}..{upper_z:.6f}"
    )

    # Derive the requested lower circular edge directly from the grounded face.
    lower_edge = None
    lower_edge_score = 1.0e99
    for i, edge in enumerate(sleeve_face.Edges()):
        bb = edge.BoundingBox()
        c = bb.center
        gt = edge.geomType()
        radius_est = 0.25 * (bb.xlen + bb.ylen)
        print(
            f"F014 boundary EDGE {i}: type={gt}, center=({c.x:.4f},{c.y:.4f},{c.z:.4f}), "
            f"radius_est={radius_est:.6f}, z={bb.zmin:.6f}..{bb.zmax:.6f}"
        )
        if gt == "CIRCLE":
            score = (
                100.0 * abs(c.z - lower_z)
                + 20.0 * abs(radius_est - sleeve_radius)
                + abs(c.x)
                + abs(c.y + 40.0)
            )
            if score < lower_edge_score:
                lower_edge_score = score
                lower_edge = edge

    if lower_edge is None:
        raise RuntimeError("Could not derive the lower circular boundary of F014")

    ebb = lower_edge.BoundingBox()
    print(
        f"Selected lower sleeve edge at z={ebb.center.z:.6f}, "
        f"diameter≈{0.5 * (ebb.xlen + ebb.ylen):.6f}"
    )

    # Measure the existing upper chamfer. The main cylinder ends at z≈20.8 and
    # the upper annular seat is at z=21 with outer radius≈3.25, giving equal
    # axial and radial setbacks of 0.2 mm. Determine these values from geometry.
    top_plane_z = None
    top_outer_radius = None
    for face in heatbreak.Faces():
        bb = face.BoundingBox()
        if face.geomType() == "PLANE" and abs(bb.zlen) < 1.0e-5 and bb.zmin > upper_z - 1.0e-6:
            radius_est = 0.25 * (bb.xlen + bb.ylen)
            if radius_est > 2.5 and radius_est <= sleeve_radius + 0.1:
                if top_plane_z is None or bb.zmin < top_plane_z:
                    top_plane_z = bb.zmin
                    top_outer_radius = radius_est

    if top_plane_z is None:
        # Grounded STEP observations provide z=21 and radius=3.25.
        top_plane_z = 21.0
        top_outer_radius = 3.25

    axial_setback = abs(top_plane_z - upper_z)
    radial_setback = abs(sleeve_radius - top_outer_radius)
    chamfer_size = 0.5 * (axial_setback + radial_setback)
    if not (0.05 <= chamfer_size <= 0.75):
        chamfer_size = 0.2

    print(
        f"Existing top chamfer measurement: axial={axial_setback:.6f}, "
        f"radial={radial_setback:.6f}; applying equal-distance chamfer "
        f"size={chamfer_size:.6f} mm"
    )

    # Apply the matching chamfer only to the lower edge of the main sleeve.
    edited_wp = cq.Workplane(obj=heatbreak).newObject([lower_edge]).chamfer(chamfer_size)
    edited_heatbreak = edited_wp.val()
    if not edited_heatbreak.isValid():
        raise RuntimeError("Chamfer operation produced an invalid heat-break solid")

    # Preserve all eight unrelated solids exactly and replace only R04.
    output_solids = []
    for i, solid in enumerate(solids):
        output_solids.append(edited_heatbreak if i == target_index else solid)
    result = cq.Compound.makeCompound(output_solids)

    print(
        f"Chamfer complete. Output solids={len(result.Solids())}, "
        f"valid={result.isValid()}; only R04 was modified."
    )
    return cq.Workplane(obj=result)