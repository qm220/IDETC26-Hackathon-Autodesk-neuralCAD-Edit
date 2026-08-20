def my_cad_function(args):
    import cadquery as cq
    import math
    import os

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
    tol = 1.0e-5

    def single_solid(shape):
        solids = shape.Solids()
        if len(solids) == 1:
            return solids[0]
        if not solids:
            raise ValueError("Operation produced no solid")
        return max(solids, key=lambda solid: solid.Volume())

    def drafted_frustum(width_x, length_y, z0, z1):
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

    outer_frustum = drafted_frustum(outer_x, outer_y, z_bottom, z_top)
    body = single_solid(outer_frustum.intersect(profile_limit(cavity=False)))

    cavity_frustum = drafted_frustum(cavity_x, cavity_y, z_bottom - 0.2, z_top)
    cavity_void = single_solid(cavity_frustum.intersect(profile_limit(cavity=True)))
    body = single_solid(body.cut(cavity_void))

    def edge_dims(edge):
        bb = edge.BoundingBox()
        return (
            bb.xmax - bb.xmin,
            bb.ymax - bb.ymin,
            bb.zmax - bb.zmin,
            max(abs(bb.xmin), abs(bb.xmax)),
            max(abs(bb.ymin), abs(bb.ymax))
        )

    def lies_on_bottom(edge):
        bb = edge.BoundingBox()
        return abs(bb.zmin - z_bottom) < tol and abs(bb.zmax - z_bottom) < tol

    def is_inner(edge):
        dx, dy, dz, max_x, max_y = edge_dims(edge)
        return max_x < 8.9 and max_y < 28.9

    def is_vertical(edge):
        dx, dy, dz, max_x, max_y = edge_dims(edge)
        return dz > 2.0 and dx < 1.6 and dy < 1.6

    def is_longitudinal_upper(edge):
        dx, dy, dz, max_x, max_y = edge_dims(edge)
        return not is_vertical(edge) and dy > 5.0 and dx < 2.0

    def is_transverse_upper(edge):
        dx, dy, dz, max_x, max_y = edge_dims(edge)
        return not is_vertical(edge) and dx > 5.0 and dy < 2.0

    def descriptor(edge):
        bb = edge.BoundingBox()
        c = edge.Center()
        return (
            c.x, c.y, c.z,
            bb.xmax - bb.xmin,
            bb.ymax - bb.ymin,
            bb.zmax - bb.zmin
        )

    def descriptor_score(edge, target):
        d = descriptor(edge)
        position = math.sqrt(
            (d[0] - target[0]) ** 2 +
            (d[1] - target[1]) ** 2 +
            (d[2] - target[2]) ** 2
        )
        size_error = abs(d[3] - target[3]) + abs(d[4] - target[4]) + abs(d[5] - target[5])
        return position + 0.15 * size_error

    def fillet_stage(shape, radius, predicate, label):
        candidates = [
            edge for edge in shape.Edges()
            if not lies_on_bottom(edge) and predicate(edge)
        ]
        print(label, "candidate edges:", len(candidates))
        if not candidates:
            return shape

        try:
            trial = single_solid(shape.fillet(radius, candidates))
            if trial.isValid():
                print("Applied", label, "as a group")
                return trial
        except Exception as exc:
            print(label, "group failed:", exc)

        targets = [descriptor(edge) for edge in candidates]
        current = shape
        successes = 0
        for index, target in enumerate(targets):
            fresh = [
                edge for edge in current.Edges()
                if not lies_on_bottom(edge) and predicate(edge)
            ]
            if not fresh:
                break
            edge = min(fresh, key=lambda item: descriptor_score(item, target))
            if descriptor_score(edge, target) > 5.0:
                continue
            try:
                trial = single_solid(current.fillet(radius, [edge]))
                if trial.isValid():
                    current = trial
                    successes += 1
            except Exception as exc:
                print(label, "individual", index, "failed:", exc)
        print("Applied", label, "individually to", successes, "edges")
        return current

    # Round the original edge system only. Bottom-plane edges are excluded.
    # Staging separates edge networks that the OCC fillet builder cannot
    # reliably process as one mixed group.
    body = fillet_stage(
        body, 1.0,
        lambda edge: is_inner(edge) and is_vertical(edge),
        "R1 inner vertical"
    )
    body = fillet_stage(
        body, 3.0,
        lambda edge: (not is_inner(edge)) and is_vertical(edge),
        "R3 outer vertical"
    )
    body = fillet_stage(
        body, 1.0,
        lambda edge: is_inner(edge) and is_transverse_upper(edge),
        "R1 inner transverse"
    )
    body = fillet_stage(
        body, 1.0,
        lambda edge: is_inner(edge) and is_longitudinal_upper(edge),
        "R1 inner longitudinal"
    )
    body = fillet_stage(
        body, 3.0,
        lambda edge: (not is_inner(edge)) and is_transverse_upper(edge),
        "R3 outer transverse"
    )
    body = fillet_stage(
        body, 3.0,
        lambda edge: (not is_inner(edge)) and is_longitudinal_upper(edge),
        "R3 outer longitudinal"
    )

    # Add two final-size annular bosses after scaling, drafting, and rounding.
    # Each starts at the bottom datum and overlaps the underside of the saddle
    # roof slightly to guarantee a structurally fused termination.
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