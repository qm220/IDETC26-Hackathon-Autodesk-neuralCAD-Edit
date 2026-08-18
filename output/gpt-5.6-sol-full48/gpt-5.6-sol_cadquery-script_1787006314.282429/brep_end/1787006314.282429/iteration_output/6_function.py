def my_cad_function(args):
    import cadquery as cq
    import math
    import os

    source = cq.importers.importStep(os.path.expanduser(args["input_file"]))
    source_shape = source.val()
    source_bb = source_shape.BoundingBox()
    print("Source valid:", source_shape.isValid())
    print("Source faces:", len(source_shape.Faces()))
    print("Source bbox: %.4f x %.4f x %.4f" % (source_bb.xlen, source_bb.ylen, source_bb.zlen))

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
            solids = merged.Solids()
            if len(solids) == 1:
                return solids[0]
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
                raise ValueError("fillet produced invalid solid")
            print(label + ": applied to %d edges" % len(edges))
            return result, True
        except Exception as exc:
            print(label + " failed:", exc)
            return shape, False

    def select_edges(shape, predicate):
        selected = []
        for edge in shape.Edges():
            try:
                if predicate(edge, edge.BoundingBox(), edge.Center()):
                    selected.append(edge)
            except Exception:
                pass
        return selected

    # Reconstruct the uniformly scaled 20 x 60 x 15 mm body. The bottom
    # intersections remain fixed while all outer walls taper inward by 2 deg.
    outer_shape = solid_of(
        cq.Workplane("XY")
        .workplane(offset=z_bottom)
        .rect(20.0, 60.0)
        .workplane(offset=total_height)
        .rect(20.0 - 2.0 * draft_offset, 60.0 - 2.0 * draft_offset)
        .loft(combine=True)
    )

    # Cut the scaled R42.15 upper cradle only through its central 48 mm zone,
    # retaining the two scaled 6 mm end lands.
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
    outer_shape = solid_of(outer_shape.cut(upper_cylinder.intersect(cradle_window)))

    # Apply the external upper R3 rounds before the vertical-corner rounds.
    # This avoids the failed three-way fillet ordering seen in the prior model.
    upper_edges = select_edges(
        outer_shape,
        lambda e, bb, c: (
            not is_bottom_edge(e) and
            (
                (abs(c.x) > 9.0 and bb.ylen > 0.4 and bb.zlen < 8.0) or
                (abs(c.y) > 29.0 and bb.xlen > 5.0 and bb.zlen < 2.0)
            )
        )
    )
    outer_shape, upper_outer_ok = try_fillet(
        outer_shape, 3.0, upper_edges, "R3 complete exterior upper perimeter"
    )

    # If OCC cannot solve the complete upper loop at once, solve the central
    # saddle sides and each end-cap chain in separate operations.
    if not upper_outer_ok:
        central_edges = select_edges(
            outer_shape,
            lambda e, bb, c: (
                not is_bottom_edge(e) and abs(c.x) > 9.0 and
                abs(c.y) < 23.5 and bb.ylen > 15.0 and bb.zlen > 0.2
            )
        )
        outer_shape, central_ok = try_fillet(
            outer_shape, 3.0, central_edges, "R3 central upper side edges"
        )

        end_results = []
        for sign in (-1.0, 1.0):
            end_edges = select_edges(
                outer_shape,
                lambda e, bb, c, s=sign: (
                    not is_bottom_edge(e) and c.y * s > 23.5 and
                    (
                        (abs(c.x) > 8.8 and bb.ylen > 0.4 and bb.zlen < 3.0) or
                        (c.y * s > 28.8 and bb.xlen > 5.0 and bb.zlen < 3.0)
                    )
                )
            )
            outer_shape, end_ok = try_fillet(
                outer_shape, 3.0, end_edges,
                "R3 %s-y upper end chain" % ("positive" if sign > 0 else "negative")
            )
            end_results.append(end_ok)
        upper_outer_ok = central_ok and all(end_results)

    # Round the four remaining convex exterior vertical corner chains R3.
    vertical_edges = select_edges(
        outer_shape,
        lambda e, bb, c: (
            not is_bottom_edge(e) and bb.zlen > 7.0 and
            abs(c.x) > 8.0 and abs(c.y) > 27.0
        )
    )
    outer_shape, vertical_outer_ok = try_fillet(
        outer_shape, 3.0, vertical_edges, "R3 exterior vertical corners"
    )

    # Apply R1 to the two concave land-to-cradle transitions after the R3
    # perimeter rounds, selecting the shortened transverse transition edges.
    transition_y = math.sqrt(42.15 ** 2 - (42.15 - z_top) ** 2)
    transition_edges = select_edges(
        outer_shape,
        lambda e, bb, c: (
            not is_bottom_edge(e) and bb.xlen > 4.0 and
            abs(abs(c.y) - transition_y) < 1.0 and
            bb.zmin > 5.5 and bb.zmax < 8.2
        )
    )
    outer_shape, upper_inner_ok = try_fillet(
        outer_shape, 1.0, transition_edges, "R1 upper land-to-cradle transitions"
    )

    # Bottom-open cavity. Its four wall intersections are fixed at the bottom
    # opening and taper inward by the same 2-degree draft toward the roof.
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
    y_join = math.sqrt(roof_radius ** 2 - (roof_center_z - ledge_z) ** 2)
    cavity_profile = solid_of(
        cq.Workplane("YZ")
        .moveTo(-28.0, z_bottom)
        .lineTo(28.0, z_bottom)
        .lineTo(28.0, ledge_z)
        .lineTo(y_join, ledge_z)
        .threePointArc((0.0, roof_center_z - roof_radius), (-y_join, ledge_z))
        .lineTo(-28.0, ledge_z)
        .close()
        .extrude(20.0, both=True)
    )
    cavity_tool = solid_of(cavity_frustum.intersect(cavity_profile))

    # Filleting all non-bottom edges of the removal tool produces R1 concave
    # rounds throughout the cavity while keeping both bottom loops sharp.
    cavity_edges = [e for e in cavity_tool.Edges() if not is_bottom_edge(e)]
    rounded_tool, cavity_ok = try_fillet(
        cavity_tool, 1.0, cavity_edges, "R1 all internal cavity edges"
    )
    if not cavity_ok:
        roof_edges = select_edges(
            cavity_tool,
            lambda e, bb, c: not is_bottom_edge(e) and bb.zmax > -2.5 and bb.zlen < 9.0
        )
        rounded_tool, roof_ok = try_fillet(
            cavity_tool, 1.0, roof_edges, "R1 cavity roof and ledge edges"
        )
        corner_edges = select_edges(
            rounded_tool,
            lambda e, bb, c: (
                not is_bottom_edge(e) and bb.zlen > 3.0 and
                bb.xlen < 1.5 and bb.ylen < 1.5
            )
        )
        rounded_tool, corner_ok = try_fillet(
            rounded_tool, 1.0, corner_edges, "R1 cavity vertical corners"
        )
        cavity_ok = roof_ok and corner_ok

    result_shape = solid_of(outer_shape.cut(rounded_tool))

    # Add two annular bosses at x=0, y=+/-15. Their OD is 6 mm, ID is 3 mm,
    # and each extends from z=-7.5 to slightly inside the local curved roof.
    boss_data = []
    for y_center in (-15.0, 15.0):
        local_roof_z = roof_center_z - math.sqrt(roof_radius ** 2 - y_center ** 2)
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
    outer_ok = upper_outer_ok and vertical_outer_ok

    print("Draft offset per wall at top: %.4f mm" % draft_offset)
    print("Upper R1 success:", upper_inner_ok)
    print("Exterior upper R3 success:", upper_outer_ok)
    print("Exterior vertical R3 success:", vertical_outer_ok)
    print("Exterior R3 complete:", outer_ok)
    print("Internal cavity R1 success:", cavity_ok)
    print("Boss data:", boss_data)
    print("Boss center spacing: 30.0000 mm")
    print("Boss OD/ID: 6.0000 / 3.0000 mm")
    print("Final valid:", result_shape.isValid())
    print("Final solids:", len(result_shape.Solids()))
    print("Final faces:", len(result_shape.Faces()))
    print("Final bbox: %.4f x %.4f x %.4f" % (final_bb.xlen, final_bb.ylen, final_bb.zlen))
    print("Final volume: %.4f mm^3" % result_shape.Volume())
    return wrap(result_shape)
