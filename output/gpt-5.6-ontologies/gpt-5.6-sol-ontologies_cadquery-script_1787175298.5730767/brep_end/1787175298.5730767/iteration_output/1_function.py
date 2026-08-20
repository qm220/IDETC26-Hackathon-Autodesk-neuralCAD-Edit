def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    original = model.val() if hasattr(model, "val") else model

    # The broad face opposite the existing large-radius edge is the bottom.
    # Local coordinates reconstructed from the original rounded frame:
    #   local X = global X
    #   local Y = direction along the frame height
    #   local Z = outward normal from the flat bottom
    n = cq.Vector(0.0, -0.9659258263, 0.2588190451)
    v = cq.Vector(0.0, 0.2588190451, 0.9659258263)
    bottom_center = cq.Vector(-556.6200, -431.3138, 312.7457)

    support_plane = cq.Plane(
        origin=bottom_center,
        xDir=cq.Vector(1.0, 0.0, 0.0),
        normal=n
    )

    # Existing inner opening: 760 x 560 mm with R50 corners.
    # Offset its wall outward by 20 mm, producing an 800 x 600 mm R70 profile.
    # The support is 5 mm thick in the bottom-normal direction.
    inner_w = 760.0
    inner_h = 560.0
    inner_r = 50.0
    offset = 20.0
    support_thickness = 5.0
    transition_radius = 2.0

    outer_w = inner_w + 2.0 * offset
    outer_h = inner_h + 2.0 * offset
    outer_r = inner_r + offset

    outer_solid = (
        cq.Workplane(support_plane)
        .rect(outer_w, outer_h)
        .vertices()
        .fillet2D(outer_r)
        .extrude(support_thickness)
        .val()
    )

    inner_tool = (
        cq.Workplane(support_plane)
        .rect(inner_w, inner_h)
        .vertices()
        .fillet2D(inner_r)
        .extrude(support_thickness)
        .val()
    )

    support = outer_solid.cut(inner_tool)

    # Round only the upper, outward-facing perimeter of the support. The lower
    # perimeter is deliberately untouched so the bottom and its edges stay flat.
    def local_coordinates(point):
        d = cq.Vector(
            point.x - bottom_center.x,
            point.y - bottom_center.y,
            point.z - bottom_center.z
        )
        return d.dot(cq.Vector(1.0, 0.0, 0.0)), d.dot(v), d.dot(n)

    upper_outer_edges = []
    for edge in support.Edges():
        vertices = edge.Vertices()
        if not vertices:
            continue

        local_vertices = [local_coordinates(vertex.Center()) for vertex in vertices]
        on_upper_plane = all(abs(coords[2]) < 0.05 for coords in local_vertices)
        belongs_to_outer_profile = any(
            max(abs(coords[0]) / (outer_w / 2.0),
                abs(coords[1]) / (outer_h / 2.0)) > 0.97
            for coords in local_vertices
        )

        if on_upper_plane and belongs_to_outer_profile:
            upper_outer_edges.append(edge)

    if upper_outer_edges:
        try:
            support = support.fillet(transition_radius, upper_outer_edges)
        except Exception as exc:
            print("Upper support fillet failed; preserving support without it:", exc)

    # Fuse the continuous support to the existing frame. The original small
    # bottom-side frame fillets also form a smooth R2 transition onto the new ledge.
    result = original.fuse(support)

    print("ORIGINAL VALID:", original.isValid())
    print("SUPPORT VALID:", support.isValid())
    print("RESULT VALID:", result.isValid())
    print("RESULT SOLIDS:", len(result.Solids()))
    print("SUPPORT PARAMETERS: offset=20 mm, thickness=5 mm, top radius=2 mm")

    bb = result.BoundingBox()
    print("RESULT BBOX: x=(%.3f, %.3f) y=(%.3f, %.3f) z=(%.3f, %.3f)" %
          (bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax))

    return cq.Workplane("XY").newObject([result])