def my_cad_function(args):
    import os
    import math
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    original = imported.val()

    annular_faces = []
    for face in original.Faces():
        try:
            if face.geomType() == "PLANE" and len(face.Wires()) >= 2:
                annular_faces.append(face)
        except Exception:
            pass

    if not annular_faces:
        raise RuntimeError("Could not locate a planar annular face")

    # The broad annular face is opposite the large-radius return and therefore
    # defines the requested flat bottom datum.
    bottom_face = max(annular_faces, key=lambda f: f.Area())
    face_center = bottom_face.Center()
    bottom_normal = bottom_face.normalAt().normalized()

    solid_center = original.Center()
    toward_solid = cq.Vector(
        solid_center.x - face_center.x,
        solid_center.y - face_center.y,
        solid_center.z - face_center.z
    )

    # Orient the normal outward from the bottom. The support is extruded in the
    # opposite direction, upward into the existing frame height.
    if bottom_normal.dot(toward_solid) > 0.0:
        bottom_normal = bottom_normal.multiply(-1.0)
    top_direction = bottom_normal.multiply(-1.0)

    line_edges = []
    for edge in bottom_face.Edges():
        try:
            if edge.geomType() == "LINE" and len(edge.Vertices()) >= 2:
                line_edges.append(edge)
        except Exception:
            pass

    if not line_edges:
        raise RuntimeError("Could not determine the frame's in-plane axes")

    axis_edge = max(line_edges, key=lambda e: e.Length())
    axis_vertices = axis_edge.Vertices()
    p0 = axis_vertices[0].Center()
    p1 = axis_vertices[-1].Center()
    raw_u = cq.Vector(p1.x - p0.x, p1.y - p0.y, p1.z - p0.z).normalized()

    normal_component = top_direction.multiply(raw_u.dot(top_direction))
    u = cq.Vector(
        raw_u.x - normal_component.x,
        raw_u.y - normal_component.y,
        raw_u.z - normal_component.z
    ).normalized()
    v = top_direction.cross(u).normalized()

    def dot_point(point, direction):
        return point.x * direction.x + point.y * direction.y + point.z * direction.z

    samples = []
    for edge in original.Edges():
        for i in range(25):
            try:
                samples.append(edge.positionAt(float(i) / 24.0))
            except Exception:
                pass

    if not samples:
        samples = [vertex.Center() for vertex in original.Vertices()]

    u_values = [dot_point(point, u) for point in samples]
    v_values = [dot_point(point, v) for point in samples]
    outer_w = max(u_values) - min(u_values)
    outer_h = max(v_values) - min(v_values)
    center_u = 0.5 * (max(u_values) + min(u_values))
    center_v = 0.5 * (max(v_values) + min(v_values))

    datum_point = bottom_face.Vertices()[0].Center()
    plane_offset = dot_point(datum_point, top_direction)
    center_world = cq.Vector(
        u.x * center_u + v.x * center_v + top_direction.x * plane_offset,
        u.y * center_u + v.y * center_v + top_direction.y * plane_offset,
        u.z * center_u + v.z * center_v + top_direction.z * plane_offset
    )

    # Existing model dimensions: outer corner radius 63 mm and inner wall
    # corner radius 50 mm, giving a 13 mm radial frame width.
    frame_width = 13.0
    inner_wall_w = outer_w - 2.0 * frame_width
    inner_wall_h = outer_h - 2.0 * frame_width
    inner_wall_r = 50.0

    # Extend slightly into the existing annulus so the support reliably fuses.
    overlap = 2.0
    support_outer_w = inner_wall_w + 2.0 * overlap
    support_outer_h = inner_wall_h + 2.0 * overlap
    support_outer_r = inner_wall_r + overlap

    # A 20 mm inward ledge reduces each full opening dimension by 40 mm.
    support_inner_w = inner_wall_w - 40.0
    support_inner_h = inner_wall_h - 40.0
    support_inner_r = inner_wall_r - 20.0

    if min(support_inner_w, support_inner_h, support_inner_r) <= 0.0:
        raise ValueError("The requested 20 mm support offset is too large")
    if support_inner_w <= 2.0 * support_inner_r or support_inner_h <= 2.0 * support_inner_r:
        raise ValueError("The support offset produces an invalid rounded rectangle")

    construction_plane = cq.Plane(origin=center_world, xDir=u, normal=top_direction)

    def rounded_rectangle_wire(width, height, radius):
        x0 = -width / 2.0
        x1 = width / 2.0
        y0 = -height / 2.0
        y1 = height / 2.0
        k = radius / math.sqrt(2.0)

        return (
            cq.Workplane(construction_plane)
            .moveTo(x0 + radius, y0)
            .lineTo(x1 - radius, y0)
            .threePointArc((x1 - radius + k, y0 + radius - k), (x1, y0 + radius))
            .lineTo(x1, y1 - radius)
            .threePointArc((x1 - radius + k, y1 - radius + k), (x1 - radius, y1))
            .lineTo(x0 + radius, y1)
            .threePointArc((x0 + radius - k, y1 - radius + k), (x0, y1 - radius))
            .lineTo(x0, y0 + radius)
            .threePointArc((x0 + radius - k, y0 + radius - k), (x0 + radius, y0))
            .close()
            .wire()
            .val()
        )

    outer_wire = rounded_rectangle_wire(support_outer_w, support_outer_h, support_outer_r)
    inner_wire = rounded_rectangle_wire(support_inner_w, support_inner_h, support_inner_r)

    support_height = 5.0
    support = cq.Solid.extrudeLinear(
        outer_wire,
        [inner_wire],
        top_direction.multiply(support_height)
    )

    def local_coordinates(point):
        delta = cq.Vector(
            point.x - center_world.x,
            point.y - center_world.y,
            point.z - center_world.z
        )
        return delta.dot(u), delta.dot(v), delta.dot(top_direction)

    def rounded_boundary_distance(x, y, width, height, radius):
        ax = abs(x)
        ay = abs(y)
        straight_x = width / 2.0 - radius
        straight_y = height / 2.0 - radius
        if ax <= straight_x:
            return abs(ay - height / 2.0)
        if ay <= straight_y:
            return abs(ax - width / 2.0)
        return abs(math.hypot(ax - straight_x, ay - straight_y) - radius)

    def find_upper_inner_edges(shape):
        selected = []
        z_tolerance = 1.0e-3
        for edge in shape.Edges():
            vertices = edge.Vertices()
            if not vertices:
                continue

            local_z = [local_coordinates(vertex.Center())[2] for vertex in vertices]
            if not all(abs(z - support_height) < z_tolerance for z in local_z):
                continue

            try:
                sample = edge.positionAt(0.5)
            except Exception:
                sample = edge.Center()

            x, y, unused_z = local_coordinates(sample)
            inner_distance = rounded_boundary_distance(
                x, y, support_inner_w, support_inner_h, support_inner_r
            )
            outer_distance = rounded_boundary_distance(
                x, y, support_outer_w, support_outer_h, support_outer_r
            )

            if inner_distance < 0.05 and inner_distance < outer_distance:
                selected.append(edge)
        return selected

    # Fillet the exposed top edge of the reduced opening before union. This
    # leaves every edge on the z=0 bottom plane sharp and the underside flat.
    support_upper_inner_edges = find_upper_inner_edges(support)
    if not support_upper_inner_edges:
        raise RuntimeError("Could not identify the support upper inner edge loop")

    try:
        rounded_support = support.fillet(2.0, support_upper_inner_edges).clean()
    except Exception as exc:
        raise RuntimeError("Could not apply the 2 mm upper support fillet: %s" % str(exc))

    final_shape = original.fuse(rounded_support).clean()

    if not final_shape.isValid():
        raise RuntimeError("Final edited frame is not a valid shape")

    solids = final_shape.Solids()
    if len(solids) != 1:
        raise RuntimeError("Expected one continuous solid, found %d" % len(solids))

    print("Projected outer envelope: %.3f x %.3f mm" % (outer_w, outer_h))
    print("Existing inner wall: %.3f x %.3f mm, R%.3f" % (
        inner_wall_w, inner_wall_h, inner_wall_r
    ))
    print("Reduced bottom opening: %.3f x %.3f mm, R%.3f" % (
        support_inner_w, support_inner_h, support_inner_r
    ))
    print("Support thickness: %.3f mm" % support_height)
    print("Filleted upper support edges: %d" % len(support_upper_inner_edges))
    print("Final solid count: %d" % len(solids))
    print("Final volume: %.6f mm^3" % final_shape.Volume())

    return cq.Workplane(obj=final_shape)