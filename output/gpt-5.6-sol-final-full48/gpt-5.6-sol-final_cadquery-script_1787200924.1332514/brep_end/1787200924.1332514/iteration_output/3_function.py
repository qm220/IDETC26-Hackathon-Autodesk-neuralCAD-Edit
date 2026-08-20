def my_cad_function(args):
    import os
    import math
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    original = cq.importers.importStep(input_file).val()

    # Locate the broad planar annular face. It is opposite the existing
    # large-radius return, so it is the requested bottom datum.
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
    bottom_normal = bottom_face.normalAt().normalized()
    solid_center = original.Center()
    toward_solid = cq.Vector(
        solid_center.x - face_center.x,
        solid_center.y - face_center.y,
        solid_center.z - face_center.z
    )

    if bottom_normal.dot(toward_solid) > 0.0:
        bottom_normal = bottom_normal.multiply(-1.0)
    upward = bottom_normal.multiply(-1.0)

    # Establish in-plane axes from the longest straight edge of the datum face.
    line_edges = []
    for edge in bottom_face.Edges():
        try:
            if edge.geomType() == "LINE" and len(edge.Vertices()) >= 2:
                line_edges.append(edge)
        except Exception:
            pass

    if not line_edges:
        raise RuntimeError("Could not determine the frame in-plane axes")

    axis_edge = max(line_edges, key=lambda e: e.Length())
    vertices = axis_edge.Vertices()
    p0 = vertices[0].Center()
    p1 = vertices[-1].Center()
    raw_u = cq.Vector(p1.x - p0.x, p1.y - p0.y, p1.z - p0.z).normalized()
    raw_u = raw_u.subtract(upward.multiply(raw_u.dot(upward)))
    u = raw_u.normalized()
    v = upward.cross(u).normalized()

    def dot_point(point, direction):
        return point.x * direction.x + point.y * direction.y + point.z * direction.z

    # Sample the original boundary to obtain its projected outer envelope.
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
    plane_offset = dot_point(datum_point, upward)
    center_world = cq.Vector(
        u.x * center_u + v.x * center_v + upward.x * plane_offset,
        u.y * center_u + v.y * center_v + upward.y * plane_offset,
        u.z * center_u + v.z * center_v + upward.z * plane_offset
    )

    # Dimensions recovered from the original frame geometry.
    frame_width = 13.0
    inner_wall_w = outer_w - 2.0 * frame_width
    inner_wall_h = outer_h - 2.0 * frame_width
    inner_wall_r = 50.0

    # The ledge projects 20 mm into the opening. A small outward overlap keeps
    # the additive solid reliably fused to the existing frame.
    overlap = 2.0
    support_outer_w = inner_wall_w + 2.0 * overlap
    support_outer_h = inner_wall_h + 2.0 * overlap
    support_outer_r = inner_wall_r + overlap
    support_inner_w = inner_wall_w - 40.0
    support_inner_h = inner_wall_h - 40.0
    support_inner_r = inner_wall_r - 20.0
    support_height = 5.0
    blend_radius = 2.0

    if min(support_inner_w, support_inner_h, support_inner_r) <= 0.0:
        raise ValueError("The requested 20 mm support offset is invalid")
    if support_inner_w <= 2.0 * support_inner_r or support_inner_h <= 2.0 * support_inner_r:
        raise ValueError("The reduced rounded-rectangle opening is invalid")

    construction_plane = cq.Plane(origin=center_world, xDir=u, normal=upward)

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

    support = cq.Solid.extrudeLinear(
        outer_wire,
        [inner_wire],
        upward.multiply(support_height)
    )

    # Fuse before filleting so the selected edge is the concave junction where
    # the ledge's upper face meets the preserved original inner wall. The prior
    # version rounded the free opening edge instead of this transition.
    combined = original.fuse(support).clean()

    def local_coordinates(point):
        delta = cq.Vector(
            point.x - center_world.x,
            point.y - center_world.y,
            point.z - center_world.z
        )
        return delta.dot(u), delta.dot(v), delta.dot(upward)

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

    transition_edges = []
    for edge in combined.Edges():
        edge_vertices = edge.Vertices()
        if not edge_vertices:
            continue

        z_values = [local_coordinates(vertex.Center())[2] for vertex in edge_vertices]
        if not all(abs(z - support_height) < 1.0e-3 for z in z_values):
            continue

        try:
            sample = edge.positionAt(0.5)
        except Exception:
            sample = edge.Center()
        x, y, unused_z = local_coordinates(sample)

        if rounded_boundary_distance(
            x, y, inner_wall_w, inner_wall_h, inner_wall_r
        ) < 0.05:
            transition_edges.append(edge)

    if not transition_edges:
        raise RuntimeError(
            "Could not identify the upper support-to-inner-wall transition loop"
        )

    try:
        final_shape = combined.fillet(blend_radius, transition_edges).clean()
    except Exception as exc:
        raise RuntimeError(
            "Could not apply the 2 mm support-to-wall transition fillet: %s" % str(exc)
        )

    if not final_shape.isValid():
        raise RuntimeError("Final edited frame is not a valid shape")

    solids = final_shape.Solids()
    if len(solids) != 1:
        raise RuntimeError("Expected one continuous solid, found %d" % len(solids))

    print("Projected outer envelope: %.3f x %.3f mm" % (outer_w, outer_h))
    print("Existing inner opening: %.3f x %.3f mm, R%.3f" % (
        inner_wall_w, inner_wall_h, inner_wall_r
    ))
    print("Reduced bottom opening: %.3f x %.3f mm, R%.3f" % (
        support_inner_w, support_inner_h, support_inner_r
    ))
    print("Support vertical thickness: %.3f mm" % support_height)
    print("Support-to-wall blend radius: %.3f mm" % blend_radius)
    print("Filleted transition edges: %d" % len(transition_edges))
    print("Bottom support edges remain sharp and planar")
    print("Final solid count: %d" % len(solids))
    print("Final volume: %.6f mm^3" % final_shape.Volume())

    return cq.Workplane(obj=final_shape)