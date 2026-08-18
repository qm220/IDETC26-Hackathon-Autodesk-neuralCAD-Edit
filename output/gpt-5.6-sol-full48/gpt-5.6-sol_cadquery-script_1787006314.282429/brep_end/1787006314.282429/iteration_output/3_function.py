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
    total_height = z_top - z_bottom
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

    def is_cradle_transition(edge):
        bb = edge.BoundingBox()
        ymid = 0.5 * (bb.ymin + bb.ymax)
        return (
            bb.ylen < 0.2
            and abs(abs(ymid) - 24.0) < 0.5
            and bb.xlen > 10.0
            and bb.zmax > 6.0
        )

    def try_fillet(shape, radius, edges, label):
        shape = solid_of(shape)
        if not edges:
            print(label + ": no matching edges")
            return shape, False
        try:
            # This CadQuery build exposes Shape.fillet(), not makeFillet().
            result = solid_of(shape.fillet(radius, edges))
            if not result.isValid():
                raise ValueError("fillet produced an invalid solid")
            print(label + ": applied to %d edges" % len(edges))
            return result, True
        except Exception as exc:
            print(label + " failed:", exc)
            return shape, False

    # Rebuild the uniformly scaled body. The original 20 x 60 mm bottom
    # outline is retained as the neutral draft outline. Opposing outer walls
    # taper inward by 2 degrees toward the top.
    outer = (
        cq.Workplane("XY")
        .workplane(offset=z_bottom)
        .rect(20.0, 60.0)
        .workplane(offset=total_height)
        .rect(20.0 - 2.0 * draft_offset,
              60.0 - 2.0 * draft_offset)
        .loft(combine=True)
    )
    outer_shape = solid_of(outer)

    # R42.15 upper cylindrical cradle, limited to the central 48 mm so that
    # nominal 6 mm flat end lands remain.
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

    # Apply R3 to convex outer edges, excluding the complete bottom perimeter
    # and the two concave land/cradle transition edges.
    exterior_edges = [
        e for e in outer_shape.Edges()
        if not is_bottom_edge(e) and not is_cradle_transition(e)
    ]
    rounded_outer, outer_ok = try_fillet(
        outer_shape, 3.0, exterior_edges, "Combined R3 exterior fillet"
    )

    if not outer_ok:
        # First round the four exterior corner chains.
        corner_edges = []
        for e in outer_shape.Edges():
            bb = e.BoundingBox()
            if (not is_bottom_edge(e)
                    and bb.zlen > 10.0
                    and bb.xlen < 2.0
                    and bb.ylen < 2.0):
                corner_edges.append(e)
        rounded_outer, corner_ok = try_fillet(
            outer_shape, 3.0, corner_edges, "R3 exterior corner fillet"
        )

        # Then round regenerated upper convex perimeter edges.
        upper_edges = []
        for e in rounded_outer.Edges():
            if is_bottom_edge(e) or is_cradle_transition(e):
                continue
            bb = e.BoundingBox()
            if bb.zmax > -0.25 and bb.zlen < 9.0:
                upper_edges.append(e)
        rounded_outer, upper_ok = try_fillet(
            rounded_outer, 3.0, upper_edges, "R3 upper perimeter fillet"
        )
        outer_ok = corner_ok and upper_ok

    outer_shape = rounded_outer

    # Apply R1 to the two concave transverse transitions between the flat lands
    # and the upper cylindrical cradle.
    transition_edges = [
        e for e in outer_shape.Edges() if is_cradle_transition(e)
    ]
    outer_shape, transition_ok = try_fillet(
        outer_shape, 1.0, transition_edges,
        "R1 upper land-to-cradle fillet"
    )

    # Drafted cavity: fixed 16 x 56 mm bottom opening, narrowing toward its
    # ceiling by the same 2-degree draft on all four internal walls.
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

    # True R44.15 cylindrical cavity roof, with short z=5.5 end ledges.
    roof_radius = 44.15
    roof_center_z = 42.15
    ledge_z = 5.5
    y_join = math.sqrt(
        roof_radius * roof_radius - (roof_center_z - ledge_z) ** 2
    )
    cavity_profile = (
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
    cavity_tool = solid_of(
        cavity_frustum.intersect(solid_of(cavity_profile))
    )

    # Filleting the removal tool rounds the resulting re-entrant cavity edges.
    # Every edge on the z=-7.5 opening loop is explicitly excluded.
    cavity_edges = [
        e for e in cavity_tool.Edges() if not is_bottom_edge(e)
    ]
    rounded_tool, cavity_ok = try_fillet(
        cavity_tool, 1.0, cavity_edges,
        "Combined R1 internal cavity fillet"
    )

    if not cavity_ok:
        # Round roof/ledge intersections first.
        roof_edges = []
        for e in cavity_tool.Edges():
            if is_bottom_edge(e):
                continue
            bb = e.BoundingBox()
            if bb.zmax > -2.5 and bb.zlen < 9.0:
                roof_edges.append(e)
        rounded_tool, roof_ok = try_fillet(
            cavity_tool, 1.0, roof_edges,
            "R1 cavity roof and ledge fillet"
        )

        # Round remaining internal corner chains without touching the opening.
        internal_corners = []
        for e in rounded_tool.Edges():
            if is_bottom_edge(e):
                continue
            bb = e.BoundingBox()
            if (bb.zlen > 4.0
                    and bb.xlen < 1.5
                    and bb.ylen < 1.5):
                internal_corners.append(e)
        rounded_tool, corner_internal_ok = try_fillet(
            rounded_tool, 1.0, internal_corners,
            "R1 internal vertical corner fillet"
        )
        cavity_ok = roof_ok and corner_internal_ok

    cavity_tool = rounded_tool
    result_shape = solid_of(outer_shape.cut(cavity_tool))

    # Add two hollow D6/D3 support bosses on vertical axes. Their centers are
    # x=0, y=+/-15, hence exactly 30 mm center-to-center and centered about the
    # part origin. Each begins at the bottom datum and reaches the local curved
    # underside wall. Small overlap ensures a reliable union.
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

    result_shape = solid_of(result_shape.clean())
    final_bb = result_shape.BoundingBox()
    print("Exterior R3 success:", outer_ok)
    print("Upper transition R1 success:", transition_ok)
    print("Internal R1 success:", cavity_ok)
    print("Final valid:", result_shape.isValid())
    print("Final solids:", len(result_shape.Solids()))
    print("Final faces:", len(result_shape.Faces()))
    print("Final bbox: %.4f x %.4f x %.4f" % (
        final_bb.xlen, final_bb.ylen, final_bb.zlen
    ))
    print("Final volume: %.4f mm^3" % result_shape.Volume())
    return wrap(result_shape)
