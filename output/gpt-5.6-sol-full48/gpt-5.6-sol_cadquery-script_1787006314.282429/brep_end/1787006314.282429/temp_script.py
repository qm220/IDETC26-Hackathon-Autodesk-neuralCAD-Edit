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
    draft_angle = 2.0
    draft_offset = total_height * math.tan(math.radians(draft_angle))
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

    def rounded_rect_wire(width, length, radius, z):
        # Generate a rounded rectangular wire from the upper face of a
        # temporary filleted prism. This is compatible with CadQuery versions
        # that do not provide Workplane.fillet2D().
        prism = (
            cq.Workplane("XY")
            .box(width, length, 1.0, centered=(True, True, True))
            .edges("|Z")
            .fillet(radius)
        )
        top_face = prism.faces(">Z").val()
        wire = top_face.outerWire()
        return wire.translate(cq.Vector(0.0, 0.0, z - 0.5))

    def is_bottom_edge(edge):
        vertices = edge.Vertices()
        return bool(vertices) and all(abs(v.Z - z_bottom) < tol for v in vertices)

    def select_edges(shape, predicate):
        selected = []
        for edge in shape.Edges():
            try:
                if predicate(edge, edge.BoundingBox(), edge.Center()):
                    selected.append(edge)
            except Exception:
                pass
        return selected

    def try_fillet(shape, radius, edges, label):
        shape = solid_of(shape)
        if not edges:
            print(label + ": no matching edges")
            return shape, False
        try:
            result = solid_of(shape.fillet(radius, edges))
            if not result.isValid():
                raise ValueError("Fillet produced an invalid solid")
            print(label + ": applied to %d edges" % len(edges))
            return result, True
        except Exception as exc:
            print(label + " failed:", exc)
            return shape, False

    # Reconstruct the uniformly scaled 20 x 60 x 15 mm body. The outside
    # profiles contract toward the top by the amount required for a 2-degree
    # neutral-plane draft about the bottom datum. The R3 longitudinal corner
    # rounds are incorporated into the loft profiles while all bottom edges
    # remain sharp.
    outer_bottom_wire = rounded_rect_wire(20.0, 60.0, 3.0, z_bottom)
    outer_top_wire = rounded_rect_wire(
        20.0 - 2.0 * draft_offset,
        60.0 - 2.0 * draft_offset,
        3.0,
        z_top
    )
    outer_shape = solid_of(cq.Solid.makeLoft(
        [outer_bottom_wire, outer_top_wire], False
    ))

    # Scaled upper cradle, R42.15, with its axis parallel to X. The cutting
    # window limits it to the central 48 mm and leaves 6 mm end lands.
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

    # Round the non-bottom upper external perimeter with R3.
    upper_outer_edges = select_edges(
        outer_shape,
        lambda e, bb, c: (
            not is_bottom_edge(e)
            and bb.zlen < 8.2
            and bb.zmax > -0.5
            and (abs(c.x) > 7.0 or abs(c.y) > 27.0)
        )
    )
    outer_shape, upper_outer_ok = try_fillet(
        outer_shape, 3.0, upper_outer_edges,
        "R3 exterior upper perimeter"
    )

    # Use smaller symmetric groups if OCC cannot solve the entire upper
    # perimeter in one fillet operation.
    if not upper_outer_ok:
        side_edges = select_edges(
            outer_shape,
            lambda e, bb, c: (
                not is_bottom_edge(e)
                and abs(c.x) > 7.0
                and abs(c.y) < 24.5
                and bb.zlen < 8.2
                and bb.ylen > 2.0
            )
        )
        outer_shape, side_ok = try_fillet(
            outer_shape, 3.0, side_edges,
            "R3 central exterior saddle edges"
        )

        end_results = []
        for sign in (-1.0, 1.0):
            end_edges = select_edges(
                outer_shape,
                lambda e, bb, c, s=sign: (
                    not is_bottom_edge(e)
                    and c.y * s > 23.0
                    and bb.zlen < 4.0
                    and (abs(c.x) > 7.0 or c.y * s > 27.0)
                )
            )
            outer_shape, end_ok = try_fillet(
                outer_shape, 3.0, end_edges,
                "R3 %s-y exterior end region" % (
                    "positive" if sign > 0 else "negative"
                )
            )
            end_results.append(end_ok)
        upper_outer_ok = side_ok and all(end_results)

    # R1 concave transitions between the two flat lands and the cradle.
    transition_y = math.sqrt(42.15 ** 2 - (42.15 - z_top) ** 2)
    transition_edges = select_edges(
        outer_shape,
        lambda e, bb, c: (
            not is_bottom_edge(e)
            and bb.xlen > 2.0
            and abs(abs(c.y) - transition_y) < 1.1
            and bb.zmin > 5.2
            and bb.zmax < 8.2
        )
    )
    outer_shape, upper_inner_ok = try_fillet(
        outer_shape, 1.0, transition_edges,
        "R1 upper land-to-cradle transitions"
    )

    # Drafted bottom-open cavity. Its 16 x 56 mm opening is fixed on the
    # bottom neutral plane, while the cavity becomes narrower toward its roof.
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
        .threePointArc(
            (0.0, roof_center_z - roof_radius),
            (-y_join, ledge_z)
        )
        .lineTo(-28.0, ledge_z)
        .close()
        .extrude(20.0, both=True)
    )
    cavity_tool = solid_of(cavity_frustum.intersect(cavity_profile))

    # Filleting the non-bottom edges of the removal tool creates R1 concave
    # rounds in the finished cavity. The complete bottom opening loop is
    # explicitly excluded.
    cavity_edges = [e for e in cavity_tool.Edges() if not is_bottom_edge(e)]
    rounded_cavity_tool, cavity_ok = try_fillet(
        cavity_tool, 1.0, cavity_edges,
        "R1 all non-bottom internal cavity edges"
    )

    if not cavity_ok:
        roof_edges = select_edges(
            cavity_tool,
            lambda e, bb, c: (
                not is_bottom_edge(e)
                and bb.zmax > -2.5
                and bb.zlen < 9.0
            )
        )
        rounded_cavity_tool, roof_ok = try_fillet(
            cavity_tool, 1.0, roof_edges,
            "R1 cavity roof and ledge edges"
        )
        corner_edges = select_edges(
            rounded_cavity_tool,
            lambda e, bb, c: (
                not is_bottom_edge(e)
                and bb.zlen > 3.0
                and bb.xlen < 1.5
                and bb.ylen < 1.5
            )
        )
        rounded_cavity_tool, corner_ok = try_fillet(
            rounded_cavity_tool, 1.0, corner_edges,
            "R1 cavity internal corner chains"
        )
        cavity_ok = roof_ok and corner_ok

    result_shape = solid_of(outer_shape.cut(rounded_cavity_tool))

    # Two hollow support bosses, centered at y=+/-15 mm for 30 mm center
    # spacing. Each annulus starts at the bottom datum and slightly overlaps
    # the local R44.15 cavity ceiling to ensure a fused connection. The D3
    # holes remain open from below and stop at the top wall.
    boss_data = []
    boss_ok = True
    for y_center in (-15.0, 15.0):
        local_roof_z = roof_center_z - math.sqrt(
            roof_radius ** 2 - y_center ** 2
        )
        boss_height = local_roof_z - z_bottom + 0.15
        boss = solid_of(
            cq.Workplane("XY", origin=(0.0, y_center, z_bottom))
            .circle(3.0)
            .circle(1.5)
            .extrude(boss_height)
        )
        try:
            result_shape = solid_of(result_shape.fuse(boss))
        except Exception as exc:
            print("Boss fusion failed at y=%.3f:" % y_center, exc)
            boss_ok = False
        boss_data.append((y_center, local_roof_z, boss_height))

    result_shape = solid_of(result_shape.clean())
    final_bb = result_shape.BoundingBox()
    bottom_edges = [e for e in result_shape.Edges() if is_bottom_edge(e)]

    print("Uniform scale target bbox: 20 x 60 x 15 mm")
    print("Draft angle: %.4f degrees" % draft_angle)
    print("Draft offset per wall at top: %.4f mm" % draft_offset)
    print("Exterior longitudinal R3 encoded in rounded loft sections")
    print("Exterior upper R3 success:", upper_outer_ok)
    print("Upper transition R1 success:", upper_inner_ok)
    print("Internal cavity R1 success:", cavity_ok)
    print("Unfilleted bottom-level edge count:", len(bottom_edges))
    print("Boss creation success:", boss_ok)
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
