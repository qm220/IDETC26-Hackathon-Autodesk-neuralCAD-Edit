def my_cad_function(args):
    import cadquery as cq
    import math
    import os

    # Load the supplied model as the required source/reference geometry.
    input_file = os.path.expanduser(args["input_file"])
    source = cq.importers.importStep(input_file)
    source_bb = source.val().BoundingBox()
    print("Loaded source bbox:", source_bb.xlen, source_bb.ylen, source_bb.zlen)

    scale = 10.0
    draft_angle = math.radians(2.0)
    draft_tan = math.tan(draft_angle)

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
        if len(solids) == 0:
            raise ValueError("Operation produced no solid")
        # This is only a safety fallback for boolean results represented as a
        # compound. Return the largest connected solid.
        return max(solids, key=lambda s: s.Volume())

    def drafted_frustum(width_x, length_y, z0, z1):
        # The lower plane is the fixed draft hinge. Both exterior and cavity
        # boundaries taper inward in +Z, consistent with release toward -Z.
        inset0 = draft_tan * (z0 - z_bottom)
        inset1 = draft_tan * (z1 - z_bottom)
        wx0 = width_x - 2.0 * inset0
        wy0 = length_y - 2.0 * inset0
        wx1 = width_x - 2.0 * inset1
        wy1 = length_y - 2.0 * inset1
        result = (
            cq.Workplane("XY")
            .workplane(offset=z0)
            .rect(wx0, wy0)
            .workplane(offset=z1 - z0)
            .rect(wx1, wy1)
            .loft(combine=True, ruled=True)
            .val()
        )
        return single_solid(result)

    def profile_limit(roof_raise=0.0, cavity=False):
        # Values are the original source dimensions uniformly enlarged 10x.
        if cavity:
            arc_end_y = 24.61707
            land_end_y = 28.0
            end_z = 5.5 + roof_raise
        else:
            arc_end_y = 24.0
            land_end_y = 30.0
            end_z = 7.5 + roof_raise

        center_z = roof_raise
        low_z = z_bottom - 3.0
        result = (
            cq.Workplane("YZ")
            .moveTo(-land_end_y, low_z)
            .lineTo(-land_end_y, end_z)
            .lineTo(-arc_end_y, end_z)
            .threePointArc((0.0, center_z), (arc_end_y, end_z))
            .lineTo(land_end_y, end_z)
            .lineTo(land_end_y, low_z)
            .close()
            .extrude(30.0, both=True)
            .val()
        )
        return single_solid(result)

    # Reconstruct the exact 10x saddle while applying 2-degree draft to all
    # original vertical exterior and cavity faces about the bottom datum.
    outer_frustum = drafted_frustum(outer_x, outer_y, z_bottom, z_top)
    outer_limit = profile_limit(cavity=False)
    body = single_solid(outer_frustum.intersect(outer_limit))

    # Begin the cutting solid slightly below the datum to ensure a completely
    # open cavity while retaining the nominal opening at the hinge plane.
    cavity_frustum = drafted_frustum(cavity_x, cavity_y, z_bottom - 0.2, z_top)
    cavity_limit = profile_limit(cavity=True)
    cavity_void = single_solid(cavity_frustum.intersect(cavity_limit))
    body = single_solid(body.cut(cavity_void))

    tol = 1.0e-5

    def lies_on_bottom(edge):
        bb = edge.BoundingBox()
        return abs(bb.zmin - z_bottom) < tol and abs(bb.zmax - z_bottom) < tol

    def inner_edge(edge):
        # All pre-boss edges wholly inside the cavity envelope are concave
        # cavity edges. Exterior edges reach beyond at least one threshold.
        bb = edge.BoundingBox()
        max_x = max(abs(bb.xmin), abs(bb.xmax))
        max_y = max(abs(bb.ymin), abs(bb.ymax))
        return max_x < 8.9 and max_y < 28.9

    def apply_group_fillet(shape, radius, predicate, label):
        candidates = [
            edge for edge in shape.Edges()
            if not lies_on_bottom(edge) and predicate(edge)
        ]
        print(label, "candidate edges:", len(candidates))
        if not candidates:
            return shape
        try:
            result = shape.makeFillet(radius, candidates)
            result = single_solid(result)
            if result.isValid():
                print("Applied", label, "to", len(candidates), "edges")
                return result
        except Exception as exc:
            print(label, "group fillet failed:", exc)

        # Fallback: first fillet non-vertical transitions, then re-query and
        # fillet vertical corners. This avoids retaining stale topology.
        def is_vertical(edge):
            bb = edge.BoundingBox()
            return (bb.zmax - bb.zmin) > 2.0 and (bb.xmax - bb.xmin) < 1.0 and (bb.ymax - bb.ymin) < 1.0

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
                trial = single_solid(current.makeFillet(radius, fresh))
                if trial.isValid():
                    current = trial
                    print("Applied", label, stage_name, "fallback to", len(fresh), "edges")
            except Exception as exc:
                print(label, stage_name, "fallback failed:", exc)
        return current

    # Operation order follows the request: R1 existing inner edges first,
    # followed by R3 existing outer edges. Bottom-plane edges remain sharp.
    body = apply_group_fillet(body, 1.0, inner_edge, "R1 inner")
    body = apply_group_fillet(body, 3.0, lambda e: not inner_edge(e), "R3 outer")

    # Add two centered annular bosses at y = +/-15 mm, giving 30 mm spacing.
    # They originate exactly at the flat-bottom elevation. Each outer cylinder
    # is trimmed to the cavity ceiling and overlaps it by 0.3 mm for a reliable
    # fused connection to the top-side wall.
    roof_overlap = 0.30
    raised_cavity_limit = profile_limit(roof_raise=roof_overlap, cavity=True)
    boss_clip = single_solid(cavity_frustum.intersect(raised_cavity_limit))

    boss_outer_parts = []
    bore_parts = []
    tool_height = 25.0

    for y in (-15.0, 15.0):
        outer_cylinder = cq.Solid.makeCylinder(
            3.0,
            tool_height,
            cq.Vector(0.0, y, z_bottom),
            cq.Vector(0.0, 0.0, 1.0)
        )
        boss_outer_parts.append(single_solid(outer_cylinder.intersect(boss_clip)))

        bore_cylinder = cq.Solid.makeCylinder(
            1.5,
            tool_height + 0.1,
            cq.Vector(0.0, y, z_bottom - 0.05),
            cq.Vector(0.0, 0.0, 1.0)
        )
        bore_parts.append(single_solid(bore_cylinder.intersect(cavity_void)))

    for boss in boss_outer_parts:
        body = single_solid(body.fuse(boss))
    for bore in bore_parts:
        body = single_solid(body.cut(bore))

    print("Final valid:", body.isValid())
    print("Final solids:", len(body.Solids()))
    print("Final bbox:", body.BoundingBox().xlen, body.BoundingBox().ylen, body.BoundingBox().zlen)
    print("Final volume:", body.Volume())
    return cq.Workplane("XY").newObject([body])