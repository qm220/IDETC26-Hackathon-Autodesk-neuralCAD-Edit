def my_cad_function(args):
    import math
    import os

    # Inspect the supplied source body before rebuilding the requested edited form.
    if "input_file" in args:
        source = cq.importers.importStep(os.path.expanduser(args["input_file"]))
        source_shape = source.val()
        bb = source_shape.BoundingBox()
        print("Source valid:", source_shape.isValid())
        print("Source faces:", len(source_shape.Faces()))
        print("Source bbox: %.4f x %.4f x %.4f" % (bb.xlen, bb.ylen, bb.zlen))
        print("Source center: (%.4f, %.4f, %.4f)" % (bb.center.x, bb.center.y, bb.center.z))

    # Final, post-scale dimensions in millimetres.
    z_bottom = -7.5
    z_top = 7.5
    draft = math.radians(2.0)
    draft_offset = (z_top - z_bottom) * math.tan(draft)

    # Exterior walls: bottom is the neutral/hinge plane. The upper envelope is
    # inset so the exterior releases toward the bottom.
    outer = (
        cq.Workplane("XY")
        .workplane(offset=z_bottom)
        .rect(20.0, 60.0)
        .workplane(offset=15.0)
        .rect(20.0 - 2.0 * draft_offset, 60.0 - 2.0 * draft_offset)
        .loft(combine=True)
    )

    # Cut the central upper saddle. Its scaled radius is 42.15 and its axis is X.
    # Restrict the cut to y=+/-24 so the two 6 mm-long flat lands remain.
    cradle_cylinder = (
        cq.Workplane("YZ")
        .center(0.0, 42.15)
        .circle(42.15)
        .extrude(30.0, both=True)
    )
    cradle_window = (
        cq.Workplane("XY")
        .box(50.0, 48.0, 80.0, centered=(True, True, True))
        .translate((0.0, 0.0, 27.5))
    )
    outer = outer.cut(cradle_cylinder.intersect(cradle_window))

    # Apply R3 to exterior edges, excluding all edges on the bottom plane and
    # excluding the two concave land-to-cradle transitions.
    def is_bottom_edge(edge):
        verts = edge.Vertices()
        return bool(verts) and all(abs(v.Z - z_bottom) < 1.0e-5 for v in verts)

    def is_cradle_transition(edge):
        verts = edge.Vertices()
        if len(verts) < 2:
            return False
        ys = [v.Y for v in verts]
        zs = [v.Z for v in verts]
        xs = [v.X for v in verts]
        return (abs(abs(sum(ys) / len(ys)) - 24.0) < 0.15 and
                max(zs) > 7.35 and max(xs) - min(xs) > 10.0)

    outer_edges = [e for e in outer.val().Edges()
                   if not is_bottom_edge(e) and not is_cradle_transition(e)]
    if outer_edges:
        try:
            outer = cq.Workplane("XY").newObject([outer.val()]).fillet(3.0, outer_edges)
            print("Applied R3 exterior rounds to", len(outer_edges), "edges")
        except Exception as exc:
            print("Combined exterior fillet fallback:", exc)
            # The most important exterior rounds are the four upright corner chains.
            vertical_edges = []
            for e in outer.val().Edges():
                if is_bottom_edge(e):
                    continue
                eb = e.BoundingBox()
                if eb.zlen > 8.0 and eb.xlen < 1.0 and eb.ylen < 1.0:
                    vertical_edges.append(e)
            if vertical_edges:
                try:
                    outer = cq.Workplane("XY").newObject([outer.val()]).fillet(3.0, vertical_edges)
                except Exception as exc2:
                    print("Vertical exterior fillets skipped:", exc2)

    # Apply the smaller R1 treatment to any surviving concave cradle transitions.
    transition_edges = [e for e in outer.val().Edges() if is_cradle_transition(e)]
    if transition_edges:
        try:
            outer = cq.Workplane("XY").newObject([outer.val()]).fillet(1.0, transition_edges)
            print("Applied R1 cradle transition rounds")
        except Exception as exc:
            print("Cradle transition fillets skipped:", exc)

    # Construct the bottom-open cavity as a drafted cutting tool. The opening at
    # the neutral plane is 16 x 56. Its walls narrow upward by two degrees.
    cavity_top_width = 16.0 - 2.0 * draft_offset
    cavity_top_length = 56.0 - 2.0 * draft_offset
    cavity_frustum = (
        cq.Workplane("XY")
        .workplane(offset=z_bottom)
        .rect(16.0, 56.0)
        .workplane(offset=15.0)
        .rect(cavity_top_width, cavity_top_length)
        .loft(combine=True)
    )

    # Cavity roof: radius 44.15, coaxial with the upper cradle at z=42.15.
    # The arc joins z=5.5 ledges exactly.
    roof_radius = 44.15
    roof_center_z = 42.15
    ledge_z = 5.5
    y_join = math.sqrt(roof_radius * roof_radius -
                       (roof_center_z - ledge_z) ** 2)
    profile = [(-28.0, z_bottom), (28.0, z_bottom), (28.0, ledge_z),
               (y_join, ledge_z)]
    samples = 40
    for i in range(1, samples + 1):
        y = y_join - (2.0 * y_join * i / samples)
        z = roof_center_z - math.sqrt(roof_radius * roof_radius - y * y)
        profile.append((y, z))
    profile.extend([(-28.0, ledge_z)])

    cavity_profile = (
        cq.Workplane("YZ")
        .polyline(profile)
        .close()
        .extrude(20.0, both=True)
    )
    cavity_tool = cavity_frustum.intersect(cavity_profile)

    # R1 rounds on all cavity-tool edges except its bottom opening. Rounding the
    # convex cutter edges produces concave internal rounds after subtraction.
    cavity_round_edges = [e for e in cavity_tool.val().Edges()
                          if not is_bottom_edge(e)]
    if cavity_round_edges:
        try:
            cavity_tool = (
                cq.Workplane("XY")
                .newObject([cavity_tool.val()])
                .fillet(1.0, cavity_round_edges)
            )
            print("Applied R1 internal rounds to", len(cavity_round_edges), "edges")
        except Exception as exc:
            print("Combined internal fillet fallback:", exc)
            # Preserve the valid drafted cavity if OCC cannot resolve all corners
            # in one rolling-ball operation.

    result = outer.cut(cavity_tool)

    # Add two hollow D6 bosses at x=0, y=+/-15. Their lower ends start at the
    # bottom datum and their upper ends conform to/contact the cylindrical roof.
    for y_center in (-15.0, 15.0):
        local_roof = roof_center_z - math.sqrt(
            roof_radius * roof_radius - y_center * y_center
        )
        boss_height = local_roof - z_bottom + 0.20
        boss = (
            cq.Workplane("XY", origin=(0.0, y_center, z_bottom))
            .circle(3.0)
            .circle(1.5)
            .extrude(boss_height)
        )
        result = result.union(boss)

    final_shape = result.val()
    final_bb = final_shape.BoundingBox()
    print("Final valid:", final_shape.isValid())
    print("Final solids:", len(final_shape.Solids()))
    print("Final faces:", len(final_shape.Faces()))
    print("Final bbox: %.4f x %.4f x %.4f" %
          (final_bb.xlen, final_bb.ylen, final_bb.zlen))
    print("Final volume: %.4f mm^3" % final_shape.Volume())
    return result