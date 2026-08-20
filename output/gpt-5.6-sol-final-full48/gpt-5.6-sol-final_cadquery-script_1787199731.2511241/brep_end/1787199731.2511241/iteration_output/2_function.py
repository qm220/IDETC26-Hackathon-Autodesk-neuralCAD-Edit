def my_cad_function(args):
    import cadquery as cq
    import math
    import os

    # Load the supplied source model as required.
    input_file = os.path.expanduser(args["input_file"])
    source = cq.importers.importStep(input_file)
    source_bb = source.val().BoundingBox()
    print("Loaded source bbox:", source_bb.xlen, source_bb.ylen, source_bb.zlen)

    scale = 10.0
    draft_tan = math.tan(math.radians(2.0))

    z_bottom = -0.75 * scale
    z_top = 0.75 * scale
    outer_x = 2.0 * scale
    outer_y = 6.0 * scale
    cavity_x = 1.6 * scale
    cavity_y = 5.6 * scale

    def single_solid(shape):
        solids = shape.Solids()
        if len(solids) == 1:
            return solids[0]
        if not solids:
            raise ValueError("Operation produced no solid")
        return max(solids, key=lambda solid: solid.Volume())

    def drafted_frustum(width_x, length_y, z0, z1):
        # The dimensions at z_bottom remain fixed; boundaries taper inward
        # toward +Z by two degrees.
        inset0 = draft_tan * (z0 - z_bottom)
        inset1 = draft_tan * (z1 - z_bottom)
        result = (
            cq.Workplane("XY")
            .workplane(offset=z0)
            .rect(width_x - 2.0 * inset0, length_y - 2.0 * inset0)
            .workplane(offset=z1 - z0)
            .rect(width_x - 2.0 * inset1, length_y - 2.0 * inset1)
            .loft(combine=True, ruled=True)
            .val()
        )
        return single_solid(result)

    def profile_limit(roof_raise=0.0, cavity=False):
        if cavity:
            arc_end_y = 24.61707
            land_end_y = 28.0
            end_z = 5.5 + roof_raise
        else:
            arc_end_y = 24.0
            land_end_y = 30.0
            end_z = 7.5 + roof_raise

        low_z = z_bottom - 3.0
        result = (
            cq.Workplane("YZ")
            .moveTo(-land_end_y, low_z)
            .lineTo(-land_end_y, end_z)
            .lineTo(-arc_end_y, end_z)
            .threePointArc((0.0, roof_raise), (arc_end_y, end_z))
            .lineTo(land_end_y, end_z)
            .lineTo(land_end_y, low_z)
            .close()
            .extrude(30.0, both=True)
            .val()
        )
        return single_solid(result)

    # Reconstruct the uniformly enlarged saddle and apply draft to its outer
    # and cavity walls using the bottom plane as the neutral plane.
    outer_frustum = drafted_frustum(outer_x, outer_y, z_bottom, z_top)
    body = single_solid(outer_frustum.intersect(profile_limit(cavity=False)))

    # Extend the cutting tool below the part, while retaining the exact nominal
    # cavity opening at z_bottom.
    cavity_frustum = drafted_frustum(cavity_x, cavity_y, z_bottom - 0.2, z_top)
    cavity_limit = profile_limit(cavity=True)
    cavity_void = single_solid(cavity_frustum.intersect(cavity_limit))
    body = single_solid(body.cut(cavity_void))

    tol = 1.0e-5

    def lies_on_bottom(edge):
        bb = edge.BoundingBox()
        return abs(bb.zmin - z_bottom) < tol and abs(bb.zmax - z_bottom) < tol

    def is_inner_edge(edge):
        # Before bosses are added, cavity edges remain wholly inside these
        # limits; exposed exterior and upper-saddle edges exceed one of them.
        bb = edge.BoundingBox()
        max_x = max(abs(bb.xmin), abs(bb.xmax))
        max_y = max(abs(bb.ymin), abs(bb.ymax))
        return max_x < 8.9 and max_y < 28.9

    def is_vertical(edge):
        bb = edge.BoundingBox()
        return (
            (bb.zmax - bb.zmin) > 2.0
            and (bb.xmax - bb.xmin) < 1.5
            and (bb.ymax - bb.ymin) < 1.5
        )

    def apply_group_fillet(shape, radius, predicate, label):
        candidates = [
            edge for edge in shape.Edges()
            if not lies_on_bottom(edge) and predicate(edge)
        ]
        print(label, "candidate edges:", len(candidates))
        if not candidates:
            return shape

        # CadQuery Solid uses fillet(), not makeFillet().
        try:
            trial = single_solid(shape.fillet(radius, candidates))
            if trial.isValid():
                print("Applied", label, "as one group")
                return trial
        except Exception as exc:
            print(label, "group fillet failed:", exc)

        # Retry by topology class, re-querying after each successful operation
        # so no stale edges are passed into the kernel.
        current = shape
        for stage_name, want_vertical in (("nonvertical", False), ("vertical", True)):
            fresh = [
                edge for edge in current.Edges()
                if not lies_on_bottom(edge)
                and predicate(edge)
                and is_vertical(edge) == want_vertical
            ]
            if not fresh:
                continue
            try:
                trial = single_solid(current.fillet(radius, fresh))
                if trial.isValid():
                    current = trial
                    print("Applied", label, stage_name, "to", len(fresh), "edges")
            except Exception as exc:
                print(label, stage_name, "fillet failed:", exc)

        return current

    # Apply rounds only to pre-existing saddle edges. All edges lying wholly on
    # the flat bottom datum are deliberately excluded.
    body = apply_group_fillet(body, 1.0, is_inner_edge, "R1 inner")
    body = apply_group_fillet(body, 3.0, lambda edge: not is_inner_edge(edge), "R3 outer")

    # Two centered annular bosses, 30 mm center-to-center, with OD 6 and ID 3.
    # Their lower ends coincide with the flat-bottom elevation. Their upper
    # ends are clipped against a slightly raised cavity ceiling so they overlap
    # and fuse reliably into the top-side saddle wall.
    roof_overlap = 0.30
    raised_cavity_limit = profile_limit(roof_raise=roof_overlap, cavity=True)
    boss_clip = single_solid(cavity_frustum.intersect(raised_cavity_limit))
    tool_height = 25.0

    for y in (-15.0, 15.0):
        outer_cylinder = cq.Solid.makeCylinder(
            3.0,
            tool_height,
            cq.Vector(0.0, y, z_bottom),
            cq.Vector(0.0, 0.0, 1.0)
        )
        boss = single_solid(outer_cylinder.intersect(boss_clip))
        body = single_solid(body.fuse(boss))

        bore_cylinder = cq.Solid.makeCylinder(
            1.5,
            tool_height + 0.1,
            cq.Vector(0.0, y, z_bottom - 0.05),
            cq.Vector(0.0, 0.0, 1.0)
        )
        body = single_solid(body.cut(bore_cylinder))

    print("Final valid:", body.isValid())
    print("Final solids:", len(body.Solids()))
    bb = body.BoundingBox()
    print("Final bbox:", bb.xlen, bb.ylen, bb.zlen)
    print("Final volume:", body.Volume())
    return cq.Workplane("XY").newObject([body])