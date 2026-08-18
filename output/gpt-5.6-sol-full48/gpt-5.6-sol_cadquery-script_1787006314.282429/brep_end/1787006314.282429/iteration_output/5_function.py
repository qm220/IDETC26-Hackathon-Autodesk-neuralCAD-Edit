def my_cad_function(args):
    import cadquery as cq
    import math
    import os

    source = cq.importers.importStep(os.path.expanduser(args["input_file"]))
    source_shape = source.val()
    source_bb = source_shape.BoundingBox()
    print("Source valid:", source_shape.isValid())
    print("Source faces:", len(source_shape.Faces()))
    print("Source bbox: %.4f x %.4f x %.4f" % (
        source_bb.xlen, source_bb.ylen, source_bb.zlen
    ))

    z_bottom = -7.5
    z_top = 7.5
    total_height = 15.0
    draft_offset = total_height * math.tan(math.radians(2.0))
    tol = 1.0e-5

    def solid_of(obj):
        shape = obj.val() if hasattr(obj, "val") else obj
        solids = shape.Solids()
        if len(solids) == 1:
            return solids[0]
        if len(solids) > 1:
            merged = solids[0]
            for other in solids[1:]:
                merged = merged.fuse(other)
            merged_solids = merged.Solids()
            if len(merged_solids) == 1:
                return merged_solids[0]
        raise ValueError("Expected one solid, found %d" % len(solids))

    def wrap(shape):
        return cq.Workplane("XY").newObject([shape])

    def is_bottom_edge(edge):
        verts = edge.Vertices()
        return bool(verts) and all(abs(v.Z - z_bottom) < tol for v in verts)

    def try_fillet(shape, radius, edges, label):
        shape = solid_of(shape)
        if not edges:
            print(label + ": no matching edges")
            return shape, False
        try:
            result = solid_of(shape.fillet(radius, edges))
            if not result.isValid():
                raise ValueError("fillet produced an invalid solid")
            print(label + ": applied to %d edges" % len(edges))
            return result, True
        except Exception as exc:
            print(label + " failed:", exc)
            return shape, False

    # Reconstruct the uniformly scaled body. Both outer and internal vertical
    # walls retain their bottom intersections and taper inward by 2 degrees.
    outer_shape = solid_of(
        cq.Workplane("XY")
        .workplane(offset=z_bottom)
        .rect(20.0, 60.0)
        .workplane(offset=total_height)
        .rect(20.0 - 2.0 * draft_offset,
              60.0 - 2.0 * draft_offset)
        .loft(combine=True)
    )

    # Scaled R42.15 upper cradle with the original scaled 6 mm end lands.
    upper_cylinder = solid_of(
        cq.Workplane("YZ")
        .center(0.0, 42.15)
        .circle(42.15)
        .extrude(30.0, both=True)
    )
    cradle_window = solid_of(
        cq.Workplane("XY")
        .box(50.0, 48.0, 80.0, centered=(True, True, True))
        .translate((0.0, 0.0, 27.5))
    )
    outer_shape = solid_of(
        outer_shape.cut(upper_cylinder.intersect(cradle_window))
    )

    # Fillet the two concave transitions between the flat lands and cradle.
    # The previous selector was too restrictive and missed these transverse
    # edges. Select using the transition's position, elevation, and x extent.
    transition_y = math.sqrt(
        42.15 * 42.15 - (42.15 - z_top) ** 2
    )
    transition_edges = []
    print("Nominal upper transition y: %.6f" % transition_y)
    for i, edge in enumerate(outer_shape.Edges()):
        bb = edge.BoundingBox()
        center = edge.Center()
        candidate = (
            bb.xlen > 10.0 and
            abs(abs(center.y) - transition_y) < 0.75 and
            bb.zmin > 6.0 and
            bb.zmax < 8.1
        )
        if candidate:
            transition_edges.append(edge)
            print("Upper transition candidate %d: center=(%.4f, %.4f, %.4f), bbox=(%.4f, %.4f, %.4f)" % (
                i, center.x, center.y, center.z,
                bb.xlen, bb.ylen, bb.zlen
            ))

    outer_shape, transition_ok = try_fillet(
        outer_shape, 1.0, transition_edges,
        "R1 upper land-to-cradle fillet"
    )

    # Fallback based on edge vertices if OCC reports a center displaced by
    # edge parameterization or splits either transition into multiple pieces.
    if not transition_ok:
        fallback_edges = []
        for edge in outer_shape.Edges():
            bb = edge.BoundingBox()
            verts = edge.Vertices()
            if not verts or bb.xlen < 4.0:
                continue
            mean_y = sum(v.Y for v in verts) / float(len(verts))
            mean_z = sum(v.Z for v in verts) / float(len(verts))
            if (abs(abs(mean_y) - transition_y) < 1.0 and
                    6.0 < mean_z < 8.1):
                fallback_edges.append(edge)
        outer_shape, transition_ok = try_fillet(
            outer_shape, 1.0, fallback_edges,
            "R1 upper transition fallback fillet"
        )

    # R3 external rounds, excluding every edge on the bottom datum.
    exterior_edges = []
    for edge in outer_shape.Edges():
        if is_bottom_edge(edge):
            continue
        bb = edge.BoundingBox()
        center = edge.Center()
        xmid = center.x
        ymid = center.y

        vertical_corner = (
            bb.zlen > 8.0 and
            abs(xmid) > 8.0 and
            abs(ymid) > 27.0
        )
        side_upper_perimeter = (
            abs(xmid) > 8.0 and
            bb.ylen > 0.5 and
            bb.zmax > -0.5
        )
        end_upper_perimeter = (
            abs(ymid) > 27.0 and
            bb.xlen > 0.5 and
            bb.zmax > 6.0
        )
        if vertical_corner or side_upper_perimeter or end_upper_perimeter:
            exterior_edges.append(edge)

    rounded_outer, outer_ok = try_fillet(
        outer_shape, 3.0, exterior_edges,
        "R3 selected exterior fillet"
    )

    if not outer_ok:
        corner_edges = []
        for edge in outer_shape.Edges():
            if is_bottom_edge(edge):
                continue
            bb = edge.BoundingBox()
            center = edge.Center()
            if (bb.zlen > 8.0 and
                    abs(center.x) > 8.0 and
                    abs(center.y) > 27.0):
                corner_edges.append(edge)
        rounded_outer, corner_ok = try_fillet(
            outer_shape, 3.0, corner_edges,
            "R3 exterior vertical corner fillet"
        )

        upper_edges = []
        for edge in rounded_outer.Edges():
            if is_bottom_edge(edge):
                continue
            bb = edge.BoundingBox()
            center = edge.Center()
            if ((abs(center.x) > 8.0 and
                 bb.ylen > 0.5 and bb.zmax > -0.5) or
                (abs(center.y) > 27.0 and
                 bb.xlen > 0.5 and bb.zmax > 6.0)):
                upper_edges.append(edge)
        rounded_outer, upper_ok = try_fillet(
            rounded_outer, 3.0, upper_edges,
            "R3 exterior upper perimeter fillet"
        )
        outer_ok = corner_ok and upper_ok

    outer_shape = rounded_outer

    # Bottom-open cavity: 16 x 56 mm at the neutral bottom plane, narrowing
    # upward by the same 2-degree draft on all four internal walls.
    cavity_top_width = 16.0 - 2.0 * draft_offset
    cavity_top_length = 56.0 - 2.0 * draft_offset
    cavity_frustum = solid_of(
        cq.Workplane("XY")
        .workplane(offset=z_bottom)
        .rect(16.0, 56.0)
        .workplane(offset=total_height)
        .rect(cavity_top_width, cavity_top_length)
        .loft(combine=True)
    )

    roof_radius = 44.15
    roof_center_z = 42.15
    ledge_z = 5.5
    y_join = math.sqrt(
        roof_radius * roof_radius -
        (roof_center_z - ledge_z) ** 2
    )
    cavity_profile = solid_of(
        cq.Workplane("YZ")
        .moveTo(-28.0, z_bottom)
        .lineTo(28.0, z_bottom)
        .lineTo(28.0, ledge_z)
        .lineTo(y_join, ledge_z)
        .threePointArc(
            (0.0, roof_center_z - roof_radius),
            (-y_join, ledge_z)
        )
        .lineTo(-28.0, ledge_z)
        .close()
        .extrude(20.0, both=True)
    )
    cavity_tool = solid_of(cavity_frustum.intersect(cavity_profile))

    # R1 on every cavity-tool edge except the opening loop at z=-7.5. Fillets
    # on a removal tool become concave rounds in the resulting cavity.
    cavity_edges = [
        edge for edge in cavity_tool.Edges()
        if not is_bottom_edge(edge)
    ]
    rounded_tool, cavity_ok = try_fillet(
        cavity_tool, 1.0, cavity_edges,
        "R1 internal cavity fillet"
    )

    if not cavity_ok:
        roof_edges = []
        for edge in cavity_tool.Edges():
            if is_bottom_edge(edge):
                continue
            bb = edge.BoundingBox()
            if bb.zmax > -2.5 and bb.zlen < 9.0:
                roof_edges.append(edge)
        rounded_tool, roof_ok = try_fillet(
            cavity_tool, 1.0, roof_edges,
            "R1 cavity roof and ledge fillet"
        )

        internal_corners = []
        for edge in rounded_tool.Edges():
            if is_bottom_edge(edge):
                continue
            bb = edge.BoundingBox()
            if bb.zlen > 4.0 and bb.xlen < 1.5 and bb.ylen < 1.5:
                internal_corners.append(edge)
        rounded_tool, internal_corner_ok = try_fillet(
            rounded_tool, 1.0, internal_corners,
            "R1 internal vertical corner fillet"
        )
        cavity_ok = roof_ok and internal_corner_ok

    result_shape = solid_of(outer_shape.cut(rounded_tool))

    # Two concentric annular bosses, D6 outside and D3 inside, centered at
    # x=0 and y=+/-15 for 30 mm center spacing. They start at z=-7.5 and fuse
    # slightly into the underside roof without cutting the upper cradle.
    boss_data = []
    for y_center in (-15.0, 15.0):
        local_roof_z = roof_center_z - math.sqrt(
            roof_radius * roof_radius - y_center * y_center
        )
        boss_height = local_roof_z - z_bottom + 0.15
        boss = solid_of(
            cq.Workplane("XY", origin=(0.0, y_center, z_bottom))
            .circle(3.0)
            .circle(1.5)
            .extrude(boss_height)
        )
        result_shape = solid_of(result_shape.fuse(boss))
        boss_data.append((y_center, local_roof_z, boss_height))

    result_shape = solid_of(result_shape.clean())
    final_bb = result_shape.BoundingBox()

    print("Draft offset per wall at top: %.4f mm" % draft_offset)
    print("Upper R1 success:", transition_ok)
    print("Exterior R3 success:", outer_ok)
    print("Internal R1 success:", cavity_ok)
    print("Boss data:", boss_data)
    print("Boss center spacing: 30.0000 mm")
    print("Boss OD/ID: 6.0000 / 3.0000 mm")
    print("Final valid:", result_shape.isValid())
    print("Final solids:", len(result_shape.Solids()))
    print("Final faces:", len(result_shape.Faces()))
    print("Final bbox: %.4f x %.4f x %.4f" % (
        final_bb.xlen, final_bb.ylen, final_bb.zlen
    ))
    print("Final volume: %.4f mm^3" % result_shape.Volume())
    return wrap(result_shape)
