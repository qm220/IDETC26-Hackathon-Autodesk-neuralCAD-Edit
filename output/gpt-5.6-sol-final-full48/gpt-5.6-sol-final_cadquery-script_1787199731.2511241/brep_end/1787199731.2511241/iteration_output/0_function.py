def my_cad_function(args):
    import math
    import os

    # Load the supplied source model as the dimensional/reference input.
    input_file = os.path.expanduser(args["input_file"])
    source = cq.importers.importStep(input_file)
    source_shape = source.val()
    source_bb = source_shape.BoundingBox()
    print("Loaded source bbox:", source_bb.xlen, source_bb.ylen, source_bb.zlen)

    scale = 10.0
    draft = math.radians(2.0)
    draft_tan = math.tan(draft)

    # Scaled dimensions recovered from the source model definition.
    z_bottom = -0.75 * scale
    z_top = 0.75 * scale
    outer_x = 2.0 * scale
    outer_y = 6.0 * scale
    cavity_x = 1.6 * scale
    cavity_y = 5.6 * scale

    def drafted_frustum(width_x, length_y, z0, z1):
        # Both exterior and cavity boundaries narrow in +Z, with the bottom
        # plane acting as the fixed neutral/hinge plane.
        dx0 = draft_tan * (z0 - z_bottom)
        dx1 = draft_tan * (z1 - z_bottom)
        wx0 = width_x - 2.0 * dx0
        wy0 = length_y - 2.0 * dx0
        wx1 = width_x - 2.0 * dx1
        wy1 = length_y - 2.0 * dx1
        return (
            cq.Workplane("XY")
            .workplane(offset=z0)
            .rect(wx0, wy0)
            .workplane(offset=z1 - z0)
            .rect(wx1, wy1)
            .loft(combine=True, ruled=True)
            .val()
        )

    def upper_profile_limit(roof_raise=0.0, cavity=False):
        if not cavity:
            y_end = 24.0
            land_end = 30.0
            endpoint_z = 7.5 + roof_raise
            midpoint_z = 0.0 + roof_raise
        else:
            y_end = 24.61707
            land_end = 28.0
            endpoint_z = 5.5 + roof_raise
            midpoint_z = 0.0 + roof_raise

        z_floor = z_bottom - 2.0
        profile = (
            cq.Workplane("YZ")
            .moveTo(-land_end, z_floor)
            .lineTo(-land_end, endpoint_z)
            .lineTo(-y_end, endpoint_z)
            .threePointArc((0.0, midpoint_z), (y_end, endpoint_z))
            .lineTo(land_end, endpoint_z)
            .lineTo(land_end, z_floor)
            .close()
            .extrude(30.0, both=True)
            .val()
        )
        return profile

    # Build the scaled body and impose the 2-degree exterior draft.
    outer_frustum = drafted_frustum(outer_x, outer_y, z_bottom, z_top)
    body = outer_frustum.intersect(upper_profile_limit(cavity=False))

    # Create the bottom-open cavity with drafted inner walls and the original
    # scaled, concentric curved ceiling.
    cavity_frustum = drafted_frustum(
        cavity_x, cavity_y, z_bottom - 0.2, z_top
    )
    cavity_limit = upper_profile_limit(cavity=True)
    cavity_void = cavity_frustum.intersect(cavity_limit)
    body = body.cut(cavity_void)

    def is_bottom_edge(edge, tolerance=1.0e-4):
        bb = edge.BoundingBox()
        return abs(bb.zmin - z_bottom) < tolerance and abs(bb.zmax - z_bottom) < tolerance

    def is_inner_edge(edge):
        bb = edge.BoundingBox()
        max_abs_x = max(abs(bb.xmin), abs(bb.xmax))
        max_abs_y = max(abs(bb.ymin), abs(bb.ymax))
        return max_abs_x < 8.9 and max_abs_y < 28.9

    # Apply R1 to cavity/concave edges, excluding all edges lying in the
    # preserved flat bottom plane.
    inner_edges = [
        edge for edge in body.Edges()
        if not is_bottom_edge(edge) and is_inner_edge(edge)
    ]
    if inner_edges:
        try:
            body = body.makeFillet(1.0, inner_edges)
            print("Applied R1 to", len(inner_edges), "inner edges")
        except Exception as exc:
            print("Grouped R1 fillet failed; retaining valid pre-fillet body:", exc)

    # Re-query topology and apply R3 to convex exterior edges. Newly generated
    # inner-fillet edges remain inside the cavity envelope and are not selected.
    outer_edges = [
        edge for edge in body.Edges()
        if not is_bottom_edge(edge) and not is_inner_edge(edge)
    ]
    if outer_edges:
        try:
            body = body.makeFillet(3.0, outer_edges)
            print("Applied R3 to", len(outer_edges), "outer edges")
        except Exception as exc:
            print("Grouped R3 fillet failed; retaining valid pre-fillet body:", exc)

    # Add two vertical hollow bosses at y = +/-15 mm. Their outside portions
    # extend slightly into the cavity roof to guarantee a fused solid, while
    # the D3 bores terminate at the un-offset cavity ceiling and remain blind.
    roof_overlap = 0.30
    raised_cavity_limit = upper_profile_limit(roof_raise=roof_overlap, cavity=True)
    boss_clip = cavity_frustum.intersect(raised_cavity_limit)

    outer_bosses = None
    bore_tools = None
    boss_height = 20.0
    for y in (-15.0, 15.0):
        outer_cylinder = cq.Solid.makeCylinder(
            3.0, boss_height, cq.Vector(0.0, y, z_bottom), cq.Vector(0, 0, 1)
        )
        outer_piece = outer_cylinder.intersect(boss_clip)

        inner_cylinder = cq.Solid.makeCylinder(
            1.5, boss_height, cq.Vector(0.0, y, z_bottom - 0.05), cq.Vector(0, 0, 1)
        )
        inner_piece = inner_cylinder.intersect(cavity_void)

        outer_bosses = outer_piece if outer_bosses is None else outer_bosses.fuse(outer_piece)
        bore_tools = inner_piece if bore_tools is None else bore_tools.fuse(inner_piece)

    body = body.fuse(outer_bosses)
    body = body.cut(bore_tools)

    print("Final valid:", body.isValid())
    print("Final solids:", len(body.Solids()))
    print("Final volume:", body.Volume())
    return cq.Workplane("XY").newObject([body])