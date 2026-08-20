def my_cad_function(args):
    import os
    import math
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    original = model.val() if hasattr(model, "val") else model

    # Reconstructed local orientation of the frame. The existing edge with the
    # larger radius is on the top side; n points outward from the opposite,
    # flat bottom face where the new support is attached.
    n = cq.Vector(0.0, -0.9659258263, 0.2588190451)
    local_y = cq.Vector(0.0, 0.2588190451, 0.9659258263)
    local_x = cq.Vector(1.0, 0.0, 0.0)
    bottom_center = cq.Vector(-556.6200, -431.3138, 312.7457)

    support_plane = cq.Plane(
        origin=bottom_center,
        xDir=local_x,
        normal=n
    )

    # Dimensions are in millimetres. The existing inner-wall profile is
    # 760 x 560 mm with 50 mm corner radii. Offsetting it outward by 20 mm
    # gives the requested continuous support boundary.
    inner_w = 760.0
    inner_h = 560.0
    inner_r = 50.0
    wall_offset = 20.0
    support_thickness = 5.0
    upper_radius = 2.0

    outer_w = inner_w + 2.0 * wall_offset
    outer_h = inner_h + 2.0 * wall_offset
    outer_r = inner_r + wall_offset

    def rounded_rectangle(workplane, width, height, radius):
        """Create a closed rounded-rectangle wire without fillet2D()."""
        hw = width / 2.0
        hh = height / 2.0
        r = radius
        q = r / math.sqrt(2.0)

        return (
            cq.Workplane(workplane)
            .moveTo(-hw + r, -hh)
            .lineTo(hw - r, -hh)
            .threePointArc((hw - r + q, -hh + r - q), (hw, -hh + r))
            .lineTo(hw, hh - r)
            .threePointArc((hw - r + q, hh - r + q), (hw - r, hh))
            .lineTo(-hw + r, hh)
            .threePointArc((-hw + r - q, hh - r + q), (-hw, hh - r))
            .lineTo(-hw, -hh + r)
            .threePointArc((-hw + r - q, -hh + r - q), (-hw + r, -hh))
            .close()
        )

    outer_solid = rounded_rectangle(
        support_plane, outer_w, outer_h, outer_r
    ).extrude(support_thickness).val()

    # Extend the cutting tool slightly beyond both faces to avoid coincident
    # Boolean boundaries while retaining exactly flat support faces.
    cut_epsilon = 0.1
    tool_plane = cq.Plane(
        origin=bottom_center - n.multiply(cut_epsilon),
        xDir=local_x,
        normal=n
    )
    inner_tool = rounded_rectangle(
        tool_plane, inner_w, inner_h, inner_r
    ).extrude(support_thickness + 2.0 * cut_epsilon).val()

    support = outer_solid.cut(inner_tool).clean()

    def local_coordinates(point):
        delta = cq.Vector(
            point.x - bottom_center.x,
            point.y - bottom_center.y,
            point.z - bottom_center.z
        )
        return (
            delta.dot(local_x),
            delta.dot(local_y),
            delta.dot(n)
        )

    # Round only the exposed upper/outward perimeter of the added step. The
    # opposite perimeter at local Z=5 mm is deliberately left sharp, thereby
    # preserving a planar bottom and excluding all bottom-edge radii.
    upper_outer_edges = []
    for edge in support.Edges():
        vertices = edge.Vertices()
        if not vertices:
            continue

        vertex_local = [local_coordinates(v.Center()) for v in vertices]
        center_local = local_coordinates(edge.Center())
        on_upper_face = (
            all(abs(p[2]) < 0.05 for p in vertex_local)
            and abs(center_local[2]) < 0.05
        )

        profile_measure = max(
            abs(center_local[0]) / (outer_w / 2.0),
            abs(center_local[1]) / (outer_h / 2.0),
            max(
                max(abs(p[0]) / (outer_w / 2.0),
                    abs(p[1]) / (outer_h / 2.0))
                for p in vertex_local
            )
        )
        belongs_to_outer_profile = profile_measure > 0.965

        if on_upper_face and belongs_to_outer_profile:
            upper_outer_edges.append(edge)

    fillet_applied = False
    if upper_outer_edges:
        try:
            support = support.fillet(upper_radius, upper_outer_edges).clean()
            fillet_applied = True
        except Exception as exc:
            print("Upper support fillet failed:", exc)

    # The support shares and overlaps the original frame's bottom footprint,
    # producing one continuous stepped frame while preserving the original
    # non-targeted geometry.
    result = original.fuse(support).clean()

    print("ORIGINAL VALID:", original.isValid())
    print("SUPPORT VALID:", support.isValid())
    print("RESULT VALID:", result.isValid())
    print("RESULT SOLIDS:", len(result.Solids()))
    print("UPPER OUTER EDGES:", len(upper_outer_edges))
    print("R2 UPPER FILLET APPLIED:", fillet_applied)
    print("SUPPORT: inner-wall offset=20 mm, thickness=5 mm, upper radius=2 mm")

    bb = result.BoundingBox()
    print("RESULT BBOX: x=(%.3f, %.3f) y=(%.3f, %.3f) z=(%.3f, %.3f)" %
          (bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax))

    return cq.Workplane("XY").newObject([result])