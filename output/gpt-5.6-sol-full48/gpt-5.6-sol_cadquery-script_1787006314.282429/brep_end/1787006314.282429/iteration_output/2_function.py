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
        verts = edge.Vertices()
        if not verts:
            return False
        yc = sum(v.Y for v in verts) / float(len(verts))
        return (
            abs(abs(yc) - 24.0) < 0.3
            and bb.xlen > 12.0
            and bb.zmin > 5.0
        )

    def try_fillet(shape, radius, edges, label):
        shape = solid_of(shape)
        if not edges:
            print(label + ": no matching edges")
            return shape, False
        try:
            result = solid_of(shape.makeFillet(radius, edges))
            print(label + ": applied to %d edges" % len(edges))
            return result, True
        except Exception as exc:
            print(label + " failed:", exc)
            return shape, False

    # Reconstruct the scaled outer body with the bottom rectangle as the
    # neutral draft outline. Both x and y exterior walls taper inward upward.
    outer = (
        cq.Workplane("XY")
        .workplane(offset=z_bottom)
        .rect(20.0, 60.0)
        .workplane(offset=total_height)
        .rect(20.0 - 2.0 * draft_offset, 60.0 - 2.0 * draft_offset)
        .loft(combine=True)
    )
    outer_shape = solid_of(outer)

    # Cut the true R42.15 cylindrical upper cradle over the central 48 mm,
    # retaining nominal 6 mm flat lands at both longitudinal ends.
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
    cradle_tool = solid_of(upper_cylinder.intersect(cradle_window))
    outer_shape = solid_of(outer_shape.cut(cradle_tool))

    # Apply R3 to all sharp exterior edges except the complete bottom loop and
    # the concave land/cradle transitions. Extracting the Solid is essential;
    # the previous result was a Compound and therefore no fillets were made.
    exterior_edges = [
        e for e in outer_shape.Edges()
        if not is_bottom_edge(e) and not is_cradle_transition(e)
    ]
    rounded_outer, outer_ok = try_fillet(
        outer_shape, 3.0, exterior_edges, "Combined R3 exterior fillet"
    )

    if not outer_ok:
        # Robust fallback by edge families. First round the four long exterior
        # corner chains, then round the regenerated upper perimeter edges.
        vertical_edges = []
        for e in outer_shape.Edges():
            bb = e.BoundingBox()
            if (not is_bottom_edge(e) and bb.zlen > 12.0 and
                    bb.xlen < 1.5 and bb.ylen < 1.5):
                vertical_edges.append(e)
        rounded_outer, vertical_ok = try_fillet(
            outer_shape, 3.0, vertical_edges, "R3 exterior corner fillet"
        )

        upper_edges = []
        for e in rounded_outer.Edges():
            if is_bottom_edge(e) or is_cradle_transition(e):
                continue
            bb = e.BoundingBox()
            if bb.zmax > 5.0 and bb.zlen < 8.0:
                upper_edges.append(e)
        rounded_outer, upper_ok = try_fillet(
            rounded_outer, 3.0, upper_edges, "R3 upper perimeter fillet"
        )
        outer_ok = vertical_ok or upper_ok

    outer_shape = rounded_outer

    # Apply R1 to the concave upper land-to-cradle transitions.
    transition_edges = [
        e for e in outer_shape.Edges() if is_cradle_transition(e)
    ]
    outer_shape, transition_ok = try_fillet(
        outer_shape, 1.0, transition_edges, "R1 cradle transition fillet"
    )

    # Drafted cavity footprint: 16 x 56 mm at the fixed bottom opening, with
    # all four internal walls narrowing toward the cavity ceiling.
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

    # Construct a true analytic R44.15 cylindrical cavity roof instead of the
    # faceted polyline used previously. The lower circular arc joins z=5.5
    # ledges at both ends and reaches z=-2 at the longitudinal center.
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
        .threePointArc((0.0, roof_center_z - roof_radius),
                       (-y_join, ledge_z))
        .lineTo(-28.0, ledge_z)
        .close()
        .extrude(20.0, both=True)
    )
    cavity_profile_shape = solid_of(cavity_profile)
    cavity_tool = solid_of(cavity_frustum.intersect(cavity_profile_shape))

    # Filleting the convex non-bottom edges of the removal tool produces R1
    # concave rounds on all corresponding internal cavity edges. The entire
    # rectangular opening loop at z=-7.5 remains sharp.
    cavity_edges = [e for e in cavity_tool.Edges() if not is_bottom_edge(e)]
    rounded_tool, cavity_ok = try_fillet(
        cavity_tool, 1.0, cavity_edges, "Combined R1 internal fillet"
    )

    if not cavity_ok:
        # Split into upper roof/ledge edges and internal vertical corners.
        upper_internal = []
        for e in cavity_tool.Edges():
            if is_bottom_edge(e):
                continue
            bb = e.BoundingBox()
            if bb.zmin > z_bottom + 3.0 and bb.zlen < 8.0:
                upper_internal.append(e)
        rounded_tool, upper_internal_ok = try_fillet(
            cavity_tool, 1.0, upper_internal, "R1 cavity roof and ledge fillet"
        )

        vertical_internal = []
        for e in rounded_tool.Edges():
            if is_bottom_edge(e):
                continue
            bb = e.BoundingBox()
            if bb.zlen > 5.0 and bb.xlen < 1.0 and bb.ylen < 1.0:
                vertical_internal.append(e)
        rounded_tool, vertical_internal_ok = try_fillet(
            rounded_tool, 1.0, vertical_internal,
            "R1 internal vertical corner fillet"
        )
        cavity_ok = upper_internal_ok or vertical_internal_ok

    cavity_tool = rounded_tool
    result_shape = solid_of(outer_shape.cut(cavity_tool))

    # Add two hollow vertical bosses, D6 outside and D3 inside, centered at
    # x=0, y=+/-15 for 30 mm center spacing. Each starts at the bottom datum and
    # independently reaches the local underside cylindrical wall. A 0.15 mm
    # controlled overlap guarantees fusion while leaving the upper cradle intact.
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
    print("Cradle R1 success:", transition_ok)
    print("Internal R1 success:", cavity_ok)
    print("Final valid:", result_shape.isValid())
    print("Final solids:", len(result_shape.Solids()))
    print("Final faces:", len(result_shape.Faces()))
    print("Final bbox: %.4f x %.4f x %.4f" % (
        final_bb.xlen, final_bb.ylen, final_bb.zlen
    ))
    print("Final volume: %.4f mm^3" % result_shape.Volume())
    return wrap(result_shape)
