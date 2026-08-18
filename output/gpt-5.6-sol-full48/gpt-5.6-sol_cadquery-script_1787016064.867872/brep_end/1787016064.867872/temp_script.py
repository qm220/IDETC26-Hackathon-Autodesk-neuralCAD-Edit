def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    base_shape = imported.val()
    result = cq.Workplane(obj=base_shape)

    bbox = base_shape.BoundingBox()
    print("Loaded model valid:", base_shape.isValid())
    print("Existing solids:", len(base_shape.Solids()))
    print("Existing faces:", len(base_shape.Faces()))
    print("Existing volume: %.3f mm^3" % base_shape.Volume())
    print("Bounding box: x=(%.3f, %.3f), y=(%.3f, %.3f), z=(%.3f, %.3f)" %
          (bbox.xmin, bbox.xmax, bbox.ymin, bbox.ymax, bbox.zmin, bbox.zmax))

    # The original blind socket boss is centered at x=0. Add three matching
    # instances so the finished part has four bosses at 20 mm pitch.
    axis_y = cq.Vector(0, 1, 0)
    new_centers = [20.0, 40.0, 60.0]

    for x_center in new_centers:
        # Broad tapered root, overlapping the beam and boss to provide a
        # pedestal-like load-spreading transition rather than a tangent joint.
        pedestal = cq.Solid.makeCone(
            8.0,
            7.0,
            5.0,
            cq.Vector(x_center, 21.5, 4.0),
            axis_y
        )

        # Radius-7 boss from within the beam-side region to the common opening
        # plane at y=34 mm.
        boss = cq.Solid.makeCylinder(
            7.0,
            11.0,
            cq.Vector(x_center, 23.0, 4.0),
            axis_y
        )

        result = result.union(cq.Workplane(obj=pedestal))
        result = result.union(cq.Workplane(obj=boss))

    # Radius-5 blind sockets open at y=34 and terminate at y=25. Extending the
    # cutters 0.1 mm beyond the opening avoids a coincident boolean boundary.
    for x_center in new_centers:
        socket_cutter = cq.Solid.makeCylinder(
            5.0,
            9.1,
            cq.Vector(x_center, 25.0, 4.0),
            axis_y
        )
        result = result.cut(cq.Workplane(obj=socket_cutter))

    # Add four lateral outrigger legs in two opposed pairs. Their bottoms are
    # coplanar at z=-6 mm, below the original boss envelope, so they establish
    # a stable and substantially wider support footprint.
    leg_stations = [-15.0, 74.0]

    for x_center in leg_stations:
        positive_leg = (
            cq.Workplane("XY")
            .box(8.0, 20.0, 9.0, centered=(True, True, True))
            .translate((x_center, 31.0, -1.5))
        )
        negative_leg = (
            cq.Workplane("XY")
            .box(8.0, 20.0, 9.0, centered=(True, True, True))
            .translate((x_center, 3.0, -1.5))
        )

        result = result.union(positive_leg)
        result = result.union(negative_leg)

        # Triangular gusset prisms reinforce both leg roots. These are created
        # as Workplane extrusions to avoid the unsupported Face.extrude call
        # that caused the previous iteration to fail.
        positive_rib = (
            cq.Workplane("XZ", origin=(x_center, 21.0, 0.0))
            .polyline([(-4.0, 2.0), (4.0, 2.0), (0.0, 6.0)])
            .close()
            .extrude(-5.0)
        )
        negative_rib = (
            cq.Workplane("XZ", origin=(x_center, 13.0, 0.0))
            .polyline([(-4.0, 2.0), (4.0, 2.0), (0.0, 6.0)])
            .close()
            .extrude(5.0)
        )

        result = result.union(positive_rib)
        result = result.union(negative_rib)

    final_shape = result.val()
    final_bbox = final_shape.BoundingBox()
    print("Edited model valid:", final_shape.isValid())
    print("Final solids:", len(final_shape.Solids()))
    print("Final faces:", len(final_shape.Faces()))
    print("Final volume: %.3f mm^3" % final_shape.Volume())
    print("Final bounding box: x=(%.3f, %.3f), y=(%.3f, %.3f), z=(%.3f, %.3f)" %
          (final_bbox.xmin, final_bbox.xmax,
           final_bbox.ymin, final_bbox.ymax,
           final_bbox.zmin, final_bbox.zmax))

    return result
