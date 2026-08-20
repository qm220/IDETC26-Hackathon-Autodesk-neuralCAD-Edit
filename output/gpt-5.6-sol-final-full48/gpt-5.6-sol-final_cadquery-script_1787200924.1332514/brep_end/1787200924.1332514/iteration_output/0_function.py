def my_cad_function(args):
    import os
    import math

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    original = imported.val()
    bbox = original.BoundingBox()

    # The existing 10 mm outer return is on the -Z side, so the opposite
    # broad +Z annular face is the requested flat bottom datum.
    bottom_z = bbox.zmax
    support_top_z = bottom_z - 5.0

    cx = 0.5 * (bbox.xmin + bbox.xmax)
    cy = 0.5 * (bbox.ymin + bbox.ymax)

    # The source B-rep has concentric rounded rectangles with an outer corner
    # radius of 63 mm and an inner-wall corner radius of 50 mm. Thus the
    # nominal inner-wall envelope is inset 13 mm from the outer footprint.
    frame_radial_width = 13.0
    inner_wall_w = bbox.xlen - 2.0 * frame_radial_width
    inner_wall_h = bbox.ylen - 2.0 * frame_radial_width
    inner_wall_r = 50.0

    # Extend the ledge slightly into the frame to guarantee a robust union.
    overlap = 2.0
    support_outer_w = inner_wall_w + 2.0 * overlap
    support_outer_h = inner_wall_h + 2.0 * overlap
    support_outer_r = inner_wall_r + overlap

    # Exact 20 mm inward offset from the existing inner wall.
    support_inner_w = inner_wall_w - 40.0
    support_inner_h = inner_wall_h - 40.0
    support_inner_r = inner_wall_r - 20.0

    if support_inner_w <= 2.0 * support_inner_r or support_inner_h <= 2.0 * support_inner_r:
        raise ValueError("The requested 20 mm inner offset creates an invalid rounded rectangle")

    def rounded_rectangle_wire(width, height, radius, z):
        x0 = cx - width / 2.0
        x1 = cx + width / 2.0
        y0 = cy - height / 2.0
        y1 = cy + height / 2.0
        k = radius / math.sqrt(2.0)

        return (
            cq.Workplane("XY", origin=(0.0, 0.0, z))
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
        support_outer_w, support_outer_h, support_outer_r, bottom_z
    )
    inner_wire = rounded_rectangle_wire(
        support_inner_w, support_inner_h, support_inner_r, bottom_z
    )

    support = cq.Solid.extrudeLinear(
        outer_wire,
        [inner_wire],
        cq.Vector(0.0, 0.0, -5.0)
    )

    fused = original.fuse(support).clean()

    # Select only the newly generated horizontal edge loops at the upper side
    # of the support. This includes both the wall junction and reduced-opening
    # edge, while excluding all edges on the flat bottom datum.
    tol = 1.0e-4
    top_edges = []
    for edge in fused.Edges():
        vertices = edge.Vertices()
        if not vertices:
            continue
        if all(abs(v.Center().z - support_top_z) < tol for v in vertices):
            top_edges.append(edge)

    print("Original bbox: %.3f x %.3f x %.3f mm" % (bbox.xlen, bbox.ylen, bbox.zlen))
    print("Bottom datum Z: %.3f mm" % bottom_z)
    print("Support top Z: %.3f mm" % support_top_z)
    print("Nominal inner wall: %.3f x %.3f mm, R%.3f" % (inner_wall_w, inner_wall_h, inner_wall_r))
    print("Reduced lower opening: %.3f x %.3f mm, R%.3f" % (support_inner_w, support_inner_h, support_inner_r))
    print("Candidate upper support edges for R2 fillet: %d" % len(top_edges))

    if not top_edges:
        raise RuntimeError("Could not identify the upper support edge loops")

    base_wp = cq.Workplane(obj=fused)
    result = base_wp.newObject(top_edges).fillet(2.0)
    final_shape = result.val().clean()

    if not final_shape.isValid():
        raise RuntimeError("Final edited frame is not a valid solid")

    print("Final solid count: %d" % len(final_shape.Solids()))
    print("Final volume: %.6f mm^3" % final_shape.Volume())
    return cq.Workplane(obj=final_shape)
