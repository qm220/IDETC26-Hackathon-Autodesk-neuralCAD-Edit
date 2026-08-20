def my_cad_function(args):
    import os
    import math

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    original = imported.val()

    # Locate the broad planar annular face opposite the existing large-radius
    # return. This is the requested flat bottom datum.
    annular_faces = []
    for face in original.Faces():
        try:
            if face.geomType() == "PLANE" and len(face.Wires()) >= 2:
                annular_faces.append(face)
        except Exception:
            pass

    if not annular_faces:
        raise RuntimeError("Could not locate a planar annular bottom face")

    bottom_face = max(annular_faces, key=lambda f: f.Area())
    face_center = bottom_face.Center()
    bottom_normal = bottom_face.normalAt()
    bottom_normal = bottom_normal.normalized()

    # Make sure bottom_normal points out of the existing solid. The support
    # thickness then extends in the opposite direction, into the frame height.
    solid_center = original.Center()
    toward_solid = cq.Vector(
        solid_center.x - face_center.x,
        solid_center.y - face_center.y,
        solid_center.z - face_center.z
    )
    if bottom_normal.dot(toward_solid) > 0.0:
        bottom_normal = bottom_normal.multiply(-1.0)

    top_direction = bottom_normal.multiply(-1.0)

    # Derive a stable in-plane long-axis direction from the longest straight
    # edge on the broad annular face.
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
    u = cq.Vector(
        axis_vertices[-1].Center().x - axis_vertices[0].Center().x,
        axis_vertices[-1].Center().y - axis_vertices[0].Center().y,
        axis_vertices[-1].Center().z - axis_vertices[0].Center().z
    ).normalized()

    # Remove any numerical component normal to the datum plane.
    u = u.subtract(top_direction.multiply(u.dot(top_direction))).normalized()
    v = top_direction.cross(u).normalized()

    def dot_point(p, direction):
        return p.x * direction.x + p.y * direction.y + p.z * direction.z

    # Sample all edges to recover the true projected outer envelope, including
    # extrema lying in the middle of rounded corner edges.
    samples = []
    for edge in original.Edges():
        for i in range(17):
            try:
                samples.append(edge.positionAt(float(i) / 16.0))
            except Exception:
                pass

    if not samples:
        samples = [vertex.Center() for vertex in original.Vertices()]

    us = [dot_point(p, u) for p in samples]
    vs = [dot_point(p, v) for p in samples]
    outer_w = max(us) - min(us)
    outer_h = max(vs) - min(vs)
    center_u = 0.5 * (max(us) + min(us))
    center_v = 0.5 * (max(vs) + min(vs))

    # Keep the construction origin exactly on the selected bottom plane.
    plane_offset = dot_point(bottom_face.Vertices()[0].Center(), top_direction)
    center_world = cq.Vector(
        u.x * center_u + v.x * center_v + top_direction.x * plane_offset,
        u.y * center_u + v.y * center_v + top_direction.y * plane_offset,
        u.z * center_u + v.z * center_v + top_direction.z * plane_offset
    )

    # Existing geometry has a 63 mm outer plan radius and a 50 mm inner-wall
    # radius, giving a nominal 13 mm radial frame width.
    frame_width = 13.0
    inner_wall_w = outer_w - 2.0 * frame_width
    inner_wall_h = outer_h - 2.0 * frame_width
    inner_wall_r = 50.0

    # Extend 2 mm into the existing frame to make the Boolean union reliable.
    overlap = 2.0
    support_outer_w = inner_wall_w + 2.0 * overlap
    support_outer_h = inner_wall_h + 2.0 * overlap
    support_outer_r = inner_wall_r + overlap

    # Twenty-millimeter inward ledge projection.
    support_inner_w = inner_wall_w - 40.0
    support_inner_h = inner_wall_h - 40.0
    support_inner_r = inner_wall_r - 20.0

    if min(support_inner_w, support_inner_h) <= 0.0:
        raise ValueError("The requested inward support offset is too large")
    if support_inner_w <= 2.0 * support_inner_r or support_inner_h <= 2.0 * support_inner_r:
        raise ValueError("The offset produces an invalid rounded rectangle")

    construction_plane = cq.Plane(
        origin=center_world,
        xDir=u,
        normal=top_direction
    )

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

    outer_wire = rounded_rectangle_wire(
        support_outer_w, support_outer_h, support_outer_r
    )
    inner_wire = rounded_rectangle_wire(
        support_inner_w, support_inner_h, support_inner_r
    )

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
        sx = width / 2.0 - radius
        sy = height / 2.0 - radius
        if ax <= sx:
            return abs(ay - height / 2.0)
        if ay <= sy:
            return abs(ax - width / 2.0)
        return abs(math.hypot(ax - sx, ay - sy) - radius)

    # Fuse first so the support becomes one continuous part of the frame.
    fused = original.fuse(support).clean()

    # Fillet only the exposed upper lip around the reduced opening. Selecting
    # the inner loop avoids the wall-junction fragments that caused the prior
    # all-edge fillet operation to fail. Bottom edges remain untouched.
    upper_inner_edges = []
    tol = 1.0e-3
    for edge in fused.Edges():
        vertices = edge.Vertices()
        if not vertices:
            continue

        vertex_local_z = [local_coordinates(vertex.Center())[2] for vertex in vertices]
        if not all(abs(z - support_height) < tol for z in vertex_local_z):
            continue

        x, y, unused_z = local_coordinates(edge.Center())
        inner_distance = rounded_boundary_distance(
            x, y, support_inner_w, support_inner_h, support_inner_r
        )
        outer_distance = rounded_boundary_distance(
            x, y, support_outer_w, support_outer_h, support_outer_r
        )
        if inner_distance < outer_distance and inner_distance < 0.25:
            upper_inner_edges.append(edge)

    print("Projected outer envelope: %.3f x %.3f mm" % (outer_w, outer_h))
    print("Nominal inner wall: %.3f x %.3f mm, R%.3f" % (
        inner_wall_w, inner_wall_h, inner_wall_r
    ))
    print("Reduced bottom opening: %.3f x %.3f mm, R%.3f" % (
        support_inner_w, support_inner_h, support_inner_r
    ))
    print("Support thickness: %.3f mm" % support_height)
    print("Upper inner support edges selected: %d" % len(upper_inner_edges))

    final_shape = None
    if upper_inner_edges:
        try:
            final_shape = fused.fillet(2.0, upper_inner_edges).clean()
        except Exception as exc:
            print("Post-union upper fillet failed; using pre-union fallback: %s" % str(exc))

    # Fallback: round the same exposed upper lip on the support before union.
    if final_shape is None:
        support_upper_inner_edges = []
        for edge in support.Edges():
            vertices = edge.Vertices()
            if not vertices:
                continue
            vertex_local_z = [local_coordinates(vertex.Center())[2] for vertex in vertices]
            if not all(abs(z - support_height) < tol for z in vertex_local_z):
                continue

            x, y, unused_z = local_coordinates(edge.Center())
            inner_distance = rounded_boundary_distance(
                x, y, support_inner_w, support_inner_h, support_inner_r
            )
            outer_distance = rounded_boundary_distance(
                x, y, support_outer_w, support_outer_h, support_outer_r
            )
            if inner_distance < outer_distance and inner_distance < 0.25:
                support_upper_inner_edges.append(edge)

        if not support_upper_inner_edges:
            raise RuntimeError("Could not identify the support's upper inner edge loop")

        rounded_support = support.fillet(2.0, support_upper_inner_edges).clean()
        final_shape = original.fuse(rounded_support).clean()

    if not final_shape.isValid():
        raise RuntimeError("Final edited frame is not a valid shape")

    solids = final_shape.Solids()
    if len(solids) != 1:
        raise RuntimeError("Expected one continuous solid, found %d" % len(solids))

    print("Final solid count: %d" % len(solids))
    print("Final volume: %.6f mm^3" % final_shape.Volume())
    return cq.Workplane(obj=final_shape)